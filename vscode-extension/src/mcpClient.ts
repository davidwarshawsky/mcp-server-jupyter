import { ChildProcess, spawn } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import * as net from 'net';
import * as vscode from 'vscode';
import WebSocket from 'ws';

// [WEB COMPATIBILITY] Conditionally import Node.js-specific modules
let HttpsProxyAgent: any;
if (typeof process !== 'undefined' && typeof process.versions !== 'undefined' && typeof process.versions.node !== 'undefined') {
  try {
    HttpsProxyAgent = require('https-proxy-agent').HttpsProxyAgent;
  } catch (e) {
    console.warn('https-proxy-agent not found, proxy support will be disabled.');
    HttpsProxyAgent = null;
  }
}

import { McpRequest, McpResponse, ExecutionStatus, PythonEnvironment, NotebookOutput } from './types';
import { trace, context } from '@opentelemetry/api';
import { ErrorClassifier } from './errorClassifier';
import { getProxyAwareEnv, logProxyConfig } from './envUtils';

export class McpClient {
  private process?: ChildProcess;
  private ws?: WebSocket;
  private requestId = 0;
  private pendingRequests = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void }>();
  private outputChannel: vscode.OutputChannel;
  private buffer = '';
  private autoRestart = true;
  private isStarting = false;
  private isShuttingDown = false;
  private sessionToken: string | null = null; // Add this line
  private parsedHost: string | null = null; // [IIRB P0 FIX #4]
  private _onNotification = new vscode.EventEmitter<{ method: string, params: any }>();
  public readonly onNotification = this._onNotification.event;
  private _onConnectionStateChange = new vscode.EventEmitter<'connected' | 'disconnected' | 'connecting'>();
  public readonly onConnectionStateChange = this._onConnectionStateChange.event;
  private _onConnectionHealthChange = new vscode.EventEmitter<{ missedHeartbeats: number; reconnectAttempt: number }>();
  public readonly onConnectionHealthChange = this._onConnectionHealthChange.event;
  private connectionState: 'connected' | 'disconnected' | 'connecting' = 'disconnected';

  // [PHASE 3 UX POLISH] Notification throttling to prevent spam
  private notificationQueue: Array<{ method: string, params: any }> = [];
  private lastNotificationSent = 0;
  private notificationThrottleMs = 100; // Max 10 notifications per second (100ms)
  private notificationFlushTimer: NodeJS.Timeout | null = null;

  // [WEEK 1] Connection resilience
  private reconnectAttempt = 0;
  private maxReconnectAttempts = 10;
  private baseReconnectDelay = 1000; // 1 second
  private maxReconnectDelay = 32000; // 32 seconds
  private reconnectTimer: NodeJS.Timeout | null = null;
  private lastWsUrl: string | null = null;
  private heartbeatInterval: NodeJS.Timeout | null = null;
  private heartbeatTimeoutMs = 30000; // Send ping every 30s
  private lastPongReceived = Date.now();
  private missedHeartbeats = 0;
  private maxMissedHeartbeats = 3;
  private errorClassifier?: ErrorClassifier;

  constructor(context?: vscode.ExtensionContext) {
    this.outputChannel = vscode.window.createOutputChannel('MCP Jupyter Server');
    if (context) {
      this.errorClassifier = new ErrorClassifier(context);
    }
  }

  public getConnectionState(): 'connected' | 'disconnected' | 'connecting' {
    return this.connectionState;
  }

  private setConnectionState(state: 'connected' | 'disconnected' | 'connecting'): void {
    if (this.connectionState !== state) {
      this.connectionState = state;
      this._onConnectionStateChange.fire(state);
    }
  }

  public getStatus(): 'running' | 'stopped' | 'starting' {
    if (this.isStarting) return 'starting';
    // In 'connect' mode, there's no process but there is a WebSocket
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return 'running';
    if (this.process && !this.process.killed) return 'running';
    return 'stopped';
  }

  /**
   * Start the MCP server process
   */
  async start(): Promise<void> {
    if (this.process || this.isStarting) {
      return;
    }

    this.isStarting = true;
    this.isShuttingDown = false;
    this.setConnectionState('connecting');

    try {
      const config = vscode.workspace.getConfiguration('mcp-jupyter');
      const serverMode = config.get<string>('serverMode') || 'spawn';
      let wsUrl = '';

      if (serverMode === 'connect') {
        // Mode: Connect to existing server
        const remotePort = config.get<number>('remotePort') || 3000;
        const remoteHost = '127.0.0.1'; // Could make this configurable too if needed
        wsUrl = `ws://${remoteHost}:${remotePort}/ws`;
        this.outputChannel.appendLine(`Connecting to existing MCP server at ${wsUrl}...`);

        // [TOKEN HANDSHAKE] Try to read zero-config connection file
        try {
          const home = os.homedir();
          const connFile = path.join(home, '.mcp-jupyter', 'connection.json');
          if (fs.existsSync(connFile)) {
            const data = JSON.parse(fs.readFileSync(connFile, 'utf8'));
            // Prefer file config if valid
            if (data.port && data.token) {
              wsUrl = `ws://${data.host || '127.0.0.1'}:${data.port}/ws`;
              this.sessionToken = data.token;
              this.outputChannel.appendLine(`[Handshake] Using configuration from ${connFile}`);
            }
          }
        } catch (e) {
          // Ignore errors, fall back to manual config
        }

        // Connect directly without spawning
        // Use the same retry strategy as spawn mode to be resilient to timing races in tests
        this.outputChannel.appendLine('Connect mode: using default retry/backoff for WebSocket connection');
        await this.connectWebSocket(wsUrl);

      } else {
        // Mode: Spawn new server (Default)
        const pythonPath = await this.findPythonExecutable();
        const serverPath = this.findServerPath();
        // Let the Python server pick an available port (pass 0) and report it back on stderr
        wsUrl = undefined as any;

        this.outputChannel.appendLine(`Starting MCP server (WebSocket mode)...`);
        this.outputChannel.appendLine(`Python: ${pythonPath}`);
        this.outputChannel.appendLine(`Server: ${serverPath ? serverPath : '(Installed Package)'}`);
        this.outputChannel.appendLine(`Port: (auto)`);
        this.outputChannel.appendLine(`Mode: spawn`);

        // Validation
        const outputChannel = this.getOutputChannel();
        const depsOK = await import('./dependencies').then(m =>
          m.checkPythonDependencies(pythonPath, serverPath, outputChannel)
        );

        if (!depsOK) {
          throw new Error(`Python environment ${pythonPath} missing required packages (mcp, src.main).`);
        }

        const spawnOptions: any = {
          stdio: ['pipe', 'pipe', 'pipe'],
          env: getProxyAwareEnv(),  // [DUH FIX #3] Inherit proxy settings for corporate environments
        };

        if (serverPath) {
          spawnOptions.cwd = serverPath;
        }

        // Log proxy config for debugging
        logProxyConfig(this.outputChannel);

        // Spawn server with port 0 so OS assigns a free port, then read actual port from stderr [MCP_PORT]: 45231
        // NEW: Idle timeout (seconds) default to 600 (10 minutes) to avoid zombie processes if VS Code crashes
        const idleTimeout = (config.get<number>('idleTimeout') || 600).toString();
        this.process = spawn(pythonPath, ['-m', 'src.main', '--transport', 'websocket', '--port', '0', '--idle-timeout', idleTimeout], spawnOptions);

        // Create a promise that resolves when the server writes the bound port to stderr
        const portPromise: Promise<number> = new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('Timed out waiting for MCP server to report port')), 5000);

          const onData = (data: any) => {
            const txt = data.toString();
            this.outputChannel.append(`[stderr] ${txt}`);

            // Look for port
            const portMatch = txt.match(/\[MCP_PORT\]:\s*(\d+)/);
            if (portMatch) {
              clearTimeout(timeout);
              const p = parseInt(portMatch[1], 10);
              // Don't remove the listener yet, we still need the auth token
              resolve(p);
            }

            // [IIRB P0 FIX #4] Look for host (for remote dev environments)
            const hostMatch = txt.match(/\[MCP_HOST\]:\s*([\w\.\-]+)/);
            if (hostMatch) {
              this.parsedHost = hostMatch[1].trim();
              this.outputChannel.appendLine(`Detected server host: ${this.parsedHost}`);
            }

            // Look for auth token via environment variable
            const tokenMatch = txt.match(/\[MCP_SESSION_TOKEN\]:\s*(.*)/);
            if (tokenMatch) {
              this.sessionToken = tokenMatch[1].trim();
              this.outputChannel.appendLine('Successfully received auth token.');
            }
          };

          const proc = this.process!;
          proc.stderr?.on('data', onData);
          proc.on('error', (err) => {
            clearTimeout(timeout);
            reject(err);
          });
        });

        this.process.stdout?.on('data', (data) => {
          // Log stdout but don't parse it as JSON-RPC if using WebSocket
          this.outputChannel.append(`[stdout] ${data.toString()}`);
        });

        this.process.on('exit', (code, signal) => {
          this.outputChannel.appendLine(`MCP server exited: code=${code}, signal=${signal}`);
          this.handleProcessExit(code, signal);
        });

        this.process.on('error', (error) => {
          this.outputChannel.appendLine(`MCP server error: ${error.message}`);
          this.rejectAllPending(new Error(`Server process error: ${error.message}`));
        });

        // Wait for server to report its bound port, then connect
        const assignedPort = await portPromise;
        // [IIRB P0 FIX #4] Parse host from server logs instead of hardcoding 127.0.0.1
        // OLD BEHAVIOR: Hardcoded 127.0.0.1 fails in:
        // - GitHub Codespaces (bridged network)
        // - Remote SSH (forwarded ports)
        // - Docker containers (bridge mode)
        //
        // NEW BEHAVIOR: Parse host from [MCP_HOST]: ... log output
        // Falls back to 127.0.0.1 if not found (local dev)
        const parsedHost = this.parsedHost || '127.0.0.1';
        wsUrl = `ws://${parsedHost}:${assignedPort}/ws`;

        // Connect WebSocket with retry (wait for spawn)
        await this.connectWebSocket(wsUrl);
      }

      // Initialize MCP Protocol
      try {
        // [HANDOFF] We must initialize to register this client session
        const initResult = await this.sendRequest('initialize', {
          protocolVersion: '2024-11-05',
          capabilities: {},
          clientInfo: { name: 'vscode-mcp-jupyter', version: '0.1.0' }
        });

        this.sendNotification('notifications/initialized', {});
        this.outputChannel.appendLine('MCP protocol initialized');
      } catch (e) {
        this.outputChannel.appendLine(`MCP Initialization failed: ${e}`);
        throw e;
      }

      // Wait for server to initialize
      await this.waitForReady();
      this.outputChannel.appendLine('MCP server ready');
      this.setConnectionState('connected');

      // [WEEK 3] Log successful connection
      if (this.errorClassifier) {
        await this.errorClassifier.logTelemetry({ type: 'connection_success' });
      }
    } catch (error) {
      this.setConnectionState('disconnected');

      // [WEEK 3] Classify error and log telemetry
      if (this.errorClassifier) {
        const classified = this.errorClassifier.classify(error as Error);
        await this.errorClassifier.logTelemetry({
          type: 'connection_failure',
          reason: classified.reason
        });
        await this.errorClassifier.showError(classified);
      } else {
        // Fallback to generic error
        this.outputChannel.show();
        const errorMsg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(
          `Failed to start MCP server: ${errorMsg}`,
          'Show Logs',
          'Open Setup Wizard'
        ).then(choice => {
          if (choice === 'Show Logs') {
            this.outputChannel.show();
          } else if (choice === 'Open Setup Wizard') {
            vscode.commands.executeCommand('mcp-jupyter.openWalkthrough');
          }
        });
      }
      throw error;
    } finally {
      this.isStarting = false;
    }
  }

  private async getFreePort(): Promise<number> {
    return new Promise((resolve, reject) => {
      const server = net.createServer();
      server.unref();
      server.on('error', reject);
      server.listen(0, () => {
        const port = (server.address() as net.AddressInfo).port;
        server.close(() => {
          resolve(port);
        });
      });
    });
  }

  private async connectWebSocket(url: string, retries = 20, delay = 500): Promise<void> {
    // [WEEK 1] Store URL for automatic reconnection
    this.lastWsUrl = url;

    for (let i = 0; i < retries; i++) {
      try {
        await new Promise<void>((resolve, reject) => {
          // MCP WebSocket servers negotiate the 'mcp' subprotocol.
          // If we don't request it, servers may reject the upgrade or select a protocol
          // we didn't offer, causing clients (and VS Code activation) to fail.

          // [SECURITY] Include auth token in headers if available
          const headers: { [key: string]: string } = {};
          if (this.sessionToken) {
            headers['X-MCP-Token'] = this.sessionToken;
          }

          // [TRACING] Propagate OpenTelemetry trace context
          const activeContext = context.active();
          const traceParent = trace.getSpan(activeContext)?.spanContext().traceId;
          if (traceParent) {
            // This is a simplified example. A real implementation would use W3C Trace Context format.
            // For now, we'll create a basic traceparent header.
            const spanId = trace.getSpan(activeContext)?.spanContext().spanId;
            const traceFlags = trace.getSpan(activeContext)?.spanContext().traceFlags;
            if (spanId && traceFlags !== undefined) {
              headers['traceparent'] = `00-${traceParent}-${spanId}-0${traceFlags}`;
            }
          }

          // [PROXY SUPPORT] Respect VS Code HTTP proxy settings
          let agent: any;
          if (HttpsProxyAgent) {
            const proxy = vscode.workspace.getConfiguration('http').get<string>('proxy');
            agent = proxy ? new HttpsProxyAgent(proxy) : undefined;
            if (proxy) {
              this.outputChannel.appendLine(`Using proxy: ${proxy}`);
            }
          }

          // [SECURITY FIX] Append token as query parameter for WebSocket auth
          // The server middleware only checks query params for WebSocket connections
          let wsUrl = url;
          if (this.sessionToken) {
            const separator = url.includes('?') ? '&' : '?';
            wsUrl = `${url}${separator}token=${encodeURIComponent(this.sessionToken)}`;
          }

          this.ws = new WebSocket(wsUrl, ['mcp'], { headers, agent });

          this.ws.on('open', async () => {
            this.outputChannel.appendLine('WebSocket connected');
            this.setConnectionState('connected');

            // [WEEK 1] Reset reconnection state on successful connection
            this.reconnectAttempt = 0;
            this.lastPongReceived = Date.now();
            this.missedHeartbeats = 0;

            // [WEEK 1] Start heartbeat monitoring
            this.startHeartbeat();

            // Check version compatibility
            try {
              await this.checkVersionCompatibility();
            } catch (error) {
              this.outputChannel.appendLine(`Version check warning: ${error}`);
              // Don't fail connection on version mismatch, just warn
            }

            // Emit an internal reconnection notification so higher-level
            // controllers can reconcile any active executions that may
            // have completed while we were disconnected.
            this._onNotification.fire({ method: 'internal/reconnected', params: {} });
            resolve();
          });

          this.ws.on('error', (err) => {
            // Only reject if we haven't opened yet
            if (this.ws?.readyState !== WebSocket.OPEN) {
              reject(err);
            } else {
              this.outputChannel.appendLine(`WebSocket error: ${err.message}`);
            }
          });

          this.ws.on('message', (data) => {
            try {
              const response = JSON.parse(data.toString());
              this.handleResponse(response);
            } catch (e) {
              this.outputChannel.appendLine(`Failed to parse WebSocket message: ${e}`);
            }
          });

          // [WEEK 1] Handle pong for heartbeat monitoring
          this.ws.on('pong', () => {
            this.lastPongReceived = Date.now();
            this.missedHeartbeats = 0;
            // Emit health change to update status bar
            this._onConnectionHealthChange.fire({
              missedHeartbeats: 0,
              reconnectAttempt: this.reconnectAttempt
            });
          });

          this.ws.on('close', (code, reason) => {
            this.outputChannel.appendLine(`WebSocket closed: ${code} ${reason}`);

            // [WEEK 1] Stop heartbeat monitoring
            this.stopHeartbeat();

            this.ws = undefined;
            this.setConnectionState('disconnected');

            // [WEEK 1] Attempt automatic reconnection for unexpected disconnects
            if (!this.isShuttingDown && this.lastWsUrl) {
              this.outputChannel.appendLine('Connection lost. Attempting automatic reconnection...');
              this.attemptReconnection();
            } else if (!this.isShuttingDown) {
              // Only show notification if not auto-reconnecting
              vscode.window.showWarningMessage(
                'MCP server disconnected',
                'Show Logs',
                'Restart Server'
              ).then(choice => {
                if (choice === 'Show Logs') {
                  this.outputChannel.show();
                } else if (choice === 'Restart Server') {
                  vscode.commands.executeCommand('mcp-jupyter.restartServer');
                }
              });
            }
          });
        });
        return; // Connected successfully
      } catch (e) {
        this.ws = undefined; // Cleanup failed socket
        if (i === retries - 1) throw e;
        await new Promise(r => setTimeout(r, delay));
      }
    }
  }

  /**
   * Check version compatibility between client and server
   * Warns user if major versions don't match
   */
  private async checkVersionCompatibility(): Promise<void> {
    try {
      const response = await this.callTool('get_version', {});
      const serverInfo = JSON.parse(response.content[0].text);

      // Extension version (from package.json)
      const extensionVersion = '0.2.0'; // TODO: Read from package.json

      // Parse versions
      const serverMajor = parseInt(serverInfo.version.split('.')[0], 10);
      const clientMajor = parseInt(extensionVersion.split('.')[0], 10);

      this.outputChannel.appendLine(`Server version: ${serverInfo.version}`);
      this.outputChannel.appendLine(`Client version: ${extensionVersion}`);

      if (serverMajor !== clientMajor) {
        vscode.window.showWarningMessage(
          `MCP server version mismatch: server=${serverInfo.version}, client=${extensionVersion}. ` +
          `Some features may not work correctly. Consider updating.`,
          'Show Logs'
        ).then(choice => {
          if (choice === 'Show Logs') {
            this.outputChannel.show();
          }
        });
      }
    } catch (error) {
      // Version check is optional - don't fail if server doesn't support get_version yet
      this.outputChannel.appendLine(`Could not check version compatibility: ${error}`);
    }
  }

  /**
   * Stop the MCP server process
   */
  async stop(): Promise<void> {
    this.isShuttingDown = true;
    this.autoRestart = false;

    if (this.ws) {
      this.ws.close();
      this.ws = undefined;
    }

    if (this.process) {
      this.process.kill();
      this.process = undefined;
    }

    this.rejectAllPending(new Error('MCP server stopped'));
  }

  /**
   * [DUH FIX #4] Force kill the MCP server process immediately
   * 
   * Sends SIGKILL (cannot be caught) to terminate the process.
   * Used for emergency stops when SIGINT/SIGTERM don't work.
   */
  async forceKill(): Promise<void> {
    this.isShuttingDown = true;
    this.autoRestart = false;

    // Close WebSocket immediately
    if (this.ws) {
      try {
        this.ws.terminate(); // Immediate close, no handshake
      } catch {
        // Ignore errors during force close
      }
      this.ws = undefined;
    }

    // Force kill process with SIGKILL
    if (this.process) {
      try {
        // First try SIGTERM
        this.process.kill('SIGTERM');

        // Wait 500ms, then SIGKILL if still running
        await new Promise(resolve => setTimeout(resolve, 500));

        if (this.process && !this.process.killed) {
          this.process.kill('SIGKILL');
        }
      } catch {
        // Ignore errors - process may already be dead
      }
      this.process = undefined;
    }

    // Reject all pending requests
    this.rejectAllPending(new Error('MCP server force killed'));

    this.outputChannel.appendLine('[FORCE KILL] Server terminated');
  }

  /**
   * Start a kernel for a notebook
   */
  async startKernel(notebookPath: string, venvPath?: string): Promise<void> {
    return this.callTool('start_kernel', {
      notebook_path: notebookPath,
      venv_path: venvPath,
    });
  }

  /**
   * Garbage collect orphaned assets for a notebook.
   *
   * Intended to be called after notebook edits are saved to disk (e.g., cleared outputs / deleted cells).
   */
  async pruneUnusedAssets(notebookPath: string, dryRun = false): Promise<any> {
    return this.callTool('prune_unused_assets', {
      notebook_path: notebookPath,
      dry_run: dryRun,
    });
  }

  /**
   * Execute a cell asynchronously and return task ID
   */
  async runCellAsync(notebookPath: string, index: number, codeContent: string, taskId?: string): Promise<string> {
    const params: Record<string, any> = {
      notebook_path: notebookPath,
      index,
      code_override: codeContent,
    };
    // Only include task_id_override if explicitly provided
    if (taskId) {
      params.task_id_override = taskId;
    }
    const result = await this.callTool('run_cell_async', params);
    // Handle both new JSON return and legacy string return
    if (typeof result === 'string') {
      try {
        const parsed = JSON.parse(result);
        return parsed.task_id || result;
      } catch {
        return result;
      }
    }
    return result.task_id;
  }

  /**   * Submit input to a pending kernel request
   */
  async submitInput(notebookPath: string, text: string): Promise<void> {
    await this.callTool('submit_input', {
      notebook_path: notebookPath,
      text
    });
  }

  /**   * Get execution status for a task
   */
  async getExecutionStatus(notebookPath: string, taskId: string): Promise<ExecutionStatus> {
    return this.callTool('get_execution_status', {
      notebook_path: notebookPath,
      task_id: taskId,
    });
  }

  /**
   * Check if kernel is currently busy executing or has queued work
   * 
   * [PERFORMANCE FIX] Used by variable dashboard to skip polling when busy.
   * Prevents flooding the execution queue with inspection requests during long operations.
   */
  async isKernelBusy(notebookPath: string): Promise<{ is_busy: boolean; reason?: string }> {
    return this.callTool('is_kernel_busy', {
      notebook_path: notebookPath,
    });
  }

  /**
   * Check kernel resources (CPU/RAM)
   */
  async checkKernelResources(notebookPath: string): Promise<{ cpu_percent: number; memory_mb: number }> {
    const result = await this.callTool('check_kernel_resources', {
      notebook_path: notebookPath,
    });
    // Handle potential string return
    if (typeof result === 'string') {
      try {
        return JSON.parse(result);
      } catch {
        // Fallback
        return { cpu_percent: 0, memory_mb: 0 };
      }
    }
    return result;
  }

  /**
   * Get execution stream (incremental outputs)
   */
  async getExecutionStream(notebookPath: string, taskId: string, fromIndex: number = 0): Promise<{
    status: string;
    new_outputs: NotebookOutput[];
    next_index: number;
    execution_count?: number;
  }> {
    const result = await this.callTool('get_execution_stream', {
      notebook_path: notebookPath,
      task_id: taskId,
      since_output_index: fromIndex,
    });

    // Server may return either:
    // - new_outputs: [] (ideal)
    // - new_outputs: "" (queued)
    // - new_outputs: { llm_summary: string, raw_outputs: [...] } (sanitize_outputs wrapper)
    let newOutputs: any = result?.new_outputs;
    if (typeof newOutputs === 'string') {
      // queued path returns an empty string
      newOutputs = [];
    } else if (newOutputs && typeof newOutputs === 'object' && !Array.isArray(newOutputs)) {
      if (Array.isArray((newOutputs as any).raw_outputs)) {
        newOutputs = (newOutputs as any).raw_outputs;
      } else {
        // Unknown wrapper shape; best-effort fallback
        newOutputs = [];
      }
    }

    return {
      ...result,
      new_outputs: Array.isArray(newOutputs) ? newOutputs : [],
    };
  }

  /**
   * Cancel/interrupt cell execution
   */
  async cancelExecution(notebookPath: string, taskId?: string): Promise<string> {
    const result = await this.callTool('cancel_execution', {
      notebook_path: notebookPath,
      task_id: taskId,
    });
    return result;
  }

  /**
   * Reconcile executions after reconnect: ask the server for the status of
   * any task IDs that the client believes are running, and synthesize
   * notebook/status notifications for any that have completed while we were
   * disconnected.
   */
  public async reconcileExecutions(activeTaskIds: string[], notebookPath: string) {
    for (const taskId of activeTaskIds) {
      try {
        const status = await this.getExecutionStatus(notebookPath, taskId);
        if (!status) continue;
        if (status.status === 'completed' || status.status === 'error' || status.status === 'cancelled') {
          this._onNotification.fire({ method: 'notebook/status', params: { exec_id: taskId, status: status.status } });
        }
      } catch (e) {
        console.error(`Failed to reconcile task ${taskId}`, e);
      }
    }
  }

  /**
   * Fetch asset content from server as base64. Public wrapper for tools.
   */
  public async getAssetContent(assetPath: string): Promise<{ data: string }> {
    const result = await this.callTool('get_asset_content', { asset_path: assetPath });
    // Tool returns wrapper or raw; normalize to object
    if (typeof result === 'string') {
      try {
        return JSON.parse(result);
      } catch {
        return { data: result } as any;
      }
    }
    return result;
  }

  /**
   * Stop a notebook kernel
   */
  async stopKernel(notebookPath: string): Promise<void> {
    return this.callTool('stop_kernel', {
      notebook_path: notebookPath,
    });
  }

  /**
   * List available Python environments
   */
  async listEnvironments(): Promise<PythonEnvironment[]> {
    const result = await this.callTool('list_available_environments', {});

    // Result might be the array directly (if server returns list) or wrapped
    if (Array.isArray(result)) {
      return result;
    }

    // Legacy/Wrapper fallback
    return result.environments || [];
  }

  /**
   * Check if notebook needs sync (handoff protocol)
   */
  async detectSyncNeeded(notebookPath: string): Promise<any> {
    const result = await this.callTool('detect_sync_needed', {
      notebook_path: notebookPath,
    });
    // Return full result for inspection
    return result;
  }

  /**
   * Sync kernel state from disk
   */
  async syncStateFromDisk(notebookPath: string): Promise<void> {
    return this.callTool('sync_state_from_disk', {
      notebook_path: notebookPath,
    });
  }

  /**
   * Get variable manifest (Variable Dashboard)
   */
  async getVariableManifest(notebookPath: string): Promise<any[]> {
    const result = await this.callTool('get_variable_manifest', {
      notebook_path: notebookPath,
    });
    // Result can be:
    // 1) Array directly
    // 2) Wrapper object { llm_summary: string, raw_outputs: [...] }
    // 3) Stringified wrapper
    try {
      if (Array.isArray(result)) {
        return result;
      }
      // If it's a string, try to parse
      if (typeof result === 'string') {
        try {
          const parsed = JSON.parse(result);
          return this.extractManifestFromWrapper(parsed);
        } catch {
          return [];
        }
      }
      // If it's an object, try to extract
      if (typeof result === 'object' && result) {
        return this.extractManifestFromWrapper(result);
      }
    } catch (e) {
      console.warn('Failed to parse variable manifest:', e);
    }
    return [];
  }

  /**
   * Extract manifest array from sanitize_outputs wrapper
   */
  private extractManifestFromWrapper(wrapper: any): any[] {
    try {
      const llm = wrapper?.llm_summary;
      if (typeof llm === 'string') {
        // Try direct parse
        try {
          const arr = JSON.parse(llm);
          if (Array.isArray(arr)) return arr;
        } catch {
          // Fallback: extract bracketed JSON array
          const match = llm.match(/\[[\s\S]*\]/);
          if (match) {
            const arr = JSON.parse(match[0]);
            if (Array.isArray(arr)) return arr;
          }
        }
      }
      // Fallback: check raw_outputs for text/plain containing JSON
      if (Array.isArray(wrapper?.raw_outputs)) {
        for (const ro of wrapper.raw_outputs) {
          const tp = ro?.text || ro?.data?.['text/plain'];
          if (tp && typeof tp === 'string' && tp.trim().startsWith('[')) {
            try {
              const arr = JSON.parse(tp);
              if (Array.isArray(arr)) return arr;
            } catch { /* ignore */ }
          }
        }
      }
    } catch (e) {
      console.warn('Failed to extract manifest from wrapper:', e);
    }
    return [];
  }

  /**
   * Send a JSON-RPC request to the MCP server
   */
  private async sendRequest(method: string, params: any): Promise<any> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('MCP server not connected via WebSocket');
    }

    const id = ++this.requestId;
    const request: McpRequest = {
      jsonrpc: '2.0',
      id,
      method,
      params,
    };

    const promise = new Promise<any>((resolve, reject) => {
      this.pendingRequests.set(id, { resolve, reject });
    });

    const requestJson = JSON.stringify(request);
    this.ws.send(requestJson);

    return promise;
  }

  /**
   * Send a JSON-RPC notification to the MCP server
   */
  private sendNotification(method: string, params: any): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const notification = {
      jsonrpc: '2.0',
      method,
      params
    };
    this.ws.send(JSON.stringify(notification));
  }

  /**
   * Call an MCP tool
   */
  private async callTool(toolName: string, args: Record<string, any>): Promise<any> {
    // --- INTEROCEPTOR: Argument Injection ---
    // Fix "Index Blindness" by injecting the VS Code buffer structure into get_notebook_outline
    if (toolName === 'get_notebook_outline' && args.notebook_path && !args.structure_override) {
      try {
        // Find the active notebook document
        const nbDoc = vscode.workspace.notebookDocuments.find(
          nb => nb.uri.fsPath === vscode.Uri.file(args.notebook_path).fsPath
        );

        if (nbDoc) {
          // Construct structure_override from the buffer
          const structure = nbDoc.getCells().map((cell, index) => ({
            index: index,
            id: (cell.metadata as any)?.custom?.id || `buffer-${index}`,
            cell_type: cell.kind === vscode.NotebookCellKind.Markup ? 'markdown' : 'code',
            source: cell.document.getText(),
            state: (cell as any).executionSummary?.executionOrder ? 'executed' : 'fresh'
          }));

          args.structure_override = structure;
        }
      } catch (e) {
        console.error('Failed to inject structure:', e);
      }
    }

    // [FIX #2] Inject buffer hashes for detect_sync_needed to prevent split-brain race condition
    if (toolName === 'detect_sync_needed' && args.notebook_path) {
      try {
        const nbDoc = vscode.workspace.notebookDocuments.find(
          nb => nb.uri.fsPath === vscode.Uri.file(args.notebook_path).fsPath
        );

        if (nbDoc) {
          // Calculate SHA-256 hashes for all code cells in the buffer
          const crypto = await import('crypto');
          const hashes: Record<number, string> = {};

          nbDoc.getCells().forEach((cell, index) => {
            if (cell.kind === vscode.NotebookCellKind.Code) {
              const source = cell.document.getText();
              const hash = crypto.createHash('sha256').update(source).digest('hex');
              hashes[index] = hash;
            }
          });

          // Inject buffer hashes as source of truth
          args.buffer_hashes = hashes;
        }
      } catch (e) {
        console.error('Failed to inject buffer hashes:', e);
      }
    }
    // ----------------------------------------

    // Use general request mechanism
    return this.sendRequest('tools/call', {
      name: toolName,
      arguments: args
    }).then(result => {
      // FastMCP might wrap the result in { content: [...] }
      if (result && result.content && Array.isArray(result.content)) {
        // If it's a text response, extract it
        const textContent = result.content.find((c: any) => c.type === 'text');
        if (textContent) {
          try {
            // Try to see if it's JSON inside text string
            return JSON.parse(textContent.text);
          } catch {
            // Note: Legacy tools might return plain strings or objects
            // If it's not JSON, return the raw text if that's what caller expects?
            // Or return the original structure?
            // Let's assume non-JSON text output is valid for some tools.
            return textContent.text;
          }
        }
      }
      // If result is directly returned (legacy?)
      return result;
    });
  }

  /**
   * [PHASE 3] Fire notification with throttling to prevent spam.
   * Buffers notifications and sends max 10 per second (100ms apart).
   */
  private _fireNotificationThrottled(notification: { method: string, params: any }): void {
    // Priority notifications (errors, connection changes) bypass throttling
    const priorityMethods = ['internal/error', 'internal/reconnected', 'notebook/error'];
    if (priorityMethods.includes(notification.method)) {
      this._onNotification.fire(notification);
      return;
    }

    // Queue lower-priority notifications
    this.notificationQueue.push(notification);

    // Clear existing timer if any
    if (this.notificationFlushTimer) {
      clearTimeout(this.notificationFlushTimer);
    }

    // Send immediately if enough time passed
    const now = Date.now();
    if (now - this.lastNotificationSent >= this.notificationThrottleMs) {
      this._flushNotificationQueue();
    } else {
      // Schedule flush for later
      const delayMs = this.notificationThrottleMs - (now - this.lastNotificationSent);
      this.notificationFlushTimer = setTimeout(() => {
        this._flushNotificationQueue();
      }, delayMs);
    }
  }

  /**
   * Flush pending notifications to UI
   */
  private _flushNotificationQueue(): void {
    if (this.notificationQueue.length === 0) return;

    // Aggregate intermediate log lines (optional optimization)
    const toSend = this.notificationQueue.splice(0, 5); // Send up to 5 at a time

    toSend.forEach(n => {
      this._onNotification.fire(n);
    });

    this.lastNotificationSent = Date.now();

    // If more items queued, schedule next flush
    if (this.notificationQueue.length > 0) {
      this.notificationFlushTimer = setTimeout(() => {
        this._flushNotificationQueue();
      }, this.notificationThrottleMs);
    }
  }


  /**
   * Handle a JSON-RPC response or notification
   */
  private handleResponse(response: McpResponse): void {
    // Check for Notification
    if (response.method && (response.id === undefined || response.id === null)) {
      this._fireNotificationThrottled({ method: response.method, params: response.params });
      return;
    }

    // It must be a response to a request if we are here (or invalid)
    if (response.id === undefined || response.id === null) {
      // Technically this is an error in JSON-RPC if it's not a notification
      return;
    }

    const pending = this.pendingRequests.get(response.id);
    if (!pending) {
      this.outputChannel.appendLine(`Received response for unknown request ID: ${response.id}`);
      return;
    }

    this.pendingRequests.delete(response.id);

    if (response.error) {
      pending.reject(new Error(`MCP error: ${response.error.message}`));
    } else {
      // INTERCEPT PROTOCOL: Check for action signals
      try {
        if (response.result && typeof response.result === 'string') {
          try {
            const parsed = JSON.parse(response.result);
            if (parsed._mcp_action === 'apply_edit' && parsed.proposal) {
              this.handleApplyEdit(parsed.proposal);
            }
          } catch (e) { /* Not JSON */ }
        }
      } catch (e) {
        console.error('Error handling edit action:', e);
      }

      pending.resolve(response.result);
    }
  }

  private async handleApplyEdit(proposal: any) {
    if (proposal.action !== 'edit_cell') return;

    const uri = vscode.Uri.file(proposal.notebook_path);

    // We need to find the notebook document
    const notebook = vscode.workspace.notebookDocuments.find(nb => nb.uri.fsPath === uri.fsPath);
    if (!notebook) return;

    const cell = notebook.cellAt(proposal.index);
    if (!cell) return;

    // Phase 2: Trust (The Diff View)
    // Instead of auto-applying, we show a diff and ask for confirmation.

    const currentContent = cell.document.getText();
    const newContent = proposal.new_content;

    // Create temporary files for diffing
    // We use temp files to ensure the diff editor has compatible resources
    const tempDir = os.tmpdir();
    const leftPath = path.join(tempDir, `cell_${proposal.index}_current.py`);
    const rightPath = path.join(tempDir, `cell_${proposal.index}_proposal.py`);

    try {
      fs.writeFileSync(leftPath, currentContent);
      fs.writeFileSync(rightPath, newContent);

      const leftUri = vscode.Uri.file(leftPath);
      const rightUri = vscode.Uri.file(rightPath);

      // Show Diff Editor (Background)
      await vscode.commands.executeCommand(
        'vscode.diff',
        leftUri,
        rightUri,
        `Review Agent Proposal (Cell ${proposal.index + 1})`
      );

      // Modal Confirmation
      const selection = await vscode.window.showInformationMessage(
        `Agent wants to edit Cell ${proposal.index + 1}.`,
        { modal: true, detail: "Review the changes in the diff view." },
        'Accept Changes',
        'Reject'
      );

      // Close the diff editor (best effort - by reverting focus or closing active editor? Hard to do reliably via API)
      // We will just leave it open or let the user close it.

      if (selection === 'Accept Changes') {
        const edit = new vscode.WorkspaceEdit();
        // Replace the cell content
        const range = new vscode.Range(0, 0, cell.document.lineCount, 0);
        edit.replace(cell.document.uri, range, newContent);

        // Apply the edit
        const success = await vscode.workspace.applyEdit(edit);
        if (success) {
          vscode.window.showInformationMessage(`Updated Cell ${proposal.index + 1}`);
          if (proposal.id) {
            this.callTool('notify_edit_result', {
              notebook_path: proposal.notebook_path,
              proposal_id: proposal.id,
              status: 'accepted',
              message: 'User accepted edit'
            }).catch(err => console.error('Failed to notify edit result:', err));
          }
        } else {
          vscode.window.showErrorMessage('Failed to apply edit.');
          if (proposal.id) {
            this.callTool('notify_edit_result', {
              notebook_path: proposal.notebook_path,
              proposal_id: proposal.id,
              status: 'failed',
              message: 'VS Code failed to apply edit'
            }).catch(err => console.error('Failed to notify edit result:', err));
          }
        }
      } else {
        vscode.window.showInformationMessage('Edit rejected.');
        if (proposal.id) {
          this.callTool('notify_edit_result', {
            notebook_path: proposal.notebook_path,
            proposal_id: proposal.id,
            status: 'rejected',
            message: 'User rejected edit'
          }).catch(err => console.error('Failed to notify edit result:', err));
        }
      }

    } catch (e) {
      vscode.window.showErrorMessage(`Failed to present diff: ${e}`);
    } finally {
      // cleanup temp files after a short delay to allow editor to close
      setTimeout(() => {
        if (fs.existsSync(leftPath)) fs.unlinkSync(leftPath);
        if (fs.existsSync(rightPath)) fs.unlinkSync(rightPath);
      }, 5000);
    }
  }


  /**
   * [WEEK 1] Start heartbeat monitoring
   * Sends ping every 30s, tracks missed pongs
   */
  private startHeartbeat(): void {
    this.stopHeartbeat(); // Clear any existing interval

    this.heartbeatInterval = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        return;
      }

      // Check if we've missed too many heartbeats
      const timeSinceLastPong = Date.now() - this.lastPongReceived;
      if (timeSinceLastPong > this.heartbeatTimeoutMs * this.maxMissedHeartbeats) {
        this.missedHeartbeats++;
        this.outputChannel.appendLine(`⚠️ Connection unstable (${this.missedHeartbeats} missed heartbeats)`);

        // [WEEK 1] Emit health change for status bar update
        this._onConnectionHealthChange.fire({
          missedHeartbeats: this.missedHeartbeats,
          reconnectAttempt: this.reconnectAttempt
        });

        if (this.missedHeartbeats >= this.maxMissedHeartbeats) {
          this.outputChannel.appendLine('❌ Too many missed heartbeats. Closing connection.');
          this.ws.close(1000, 'Heartbeat timeout');
          return;
        }
      }

      // Send ping
      try {
        this.ws.ping();
      } catch (error) {
        this.outputChannel.appendLine(`Failed to send ping: ${error}`);
      }
    }, this.heartbeatTimeoutMs);
  }

  /**
   * [WEEK 1] Stop heartbeat monitoring
   */
  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  /**
   * [WEEK 1] Attempt automatic reconnection with exponential backoff
   */
  private async attemptReconnection(): Promise<void> {
    // Clear any pending reconnection timer
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    this.reconnectAttempt++;

    if (this.reconnectAttempt > this.maxReconnectAttempts) {
      this.outputChannel.appendLine(`❌ Max reconnection attempts (${this.maxReconnectAttempts}) reached`);
      vscode.window.showErrorMessage(
        'Failed to reconnect to MCP server after multiple attempts',
        'Show Logs',
        'Restart Server'
      ).then(choice => {
        if (choice === 'Show Logs') {
          this.outputChannel.show();
        } else if (choice === 'Restart Server') {
          this.reconnectAttempt = 0; // Reset for manual restart
          vscode.commands.executeCommand('mcp-jupyter.restartServer');
        }
      });
      return;
    }

    // Calculate exponential backoff delay with jitter
    const baseDelay = Math.min(
      this.baseReconnectDelay * Math.pow(2, this.reconnectAttempt - 1),
      this.maxReconnectDelay
    );
    const jitter = Math.random() * 0.3 * baseDelay; // ±30% jitter
    const delay = baseDelay + jitter;

    this.outputChannel.appendLine(
      `🔄 Reconnection attempt ${this.reconnectAttempt}/${this.maxReconnectAttempts} in ${Math.round(delay)}ms...`
    );

    // [WEEK 1] Emit health change for status bar update
    this._onConnectionHealthChange.fire({
      missedHeartbeats: this.missedHeartbeats,
      reconnectAttempt: this.reconnectAttempt
    });

    this.reconnectTimer = setTimeout(async () => {
      if (this.isShuttingDown || !this.lastWsUrl) {
        return;
      }

      try {
        this.setConnectionState('connecting');
        const startTime = Date.now();
        await this.connectWebSocket(this.lastWsUrl, 1, 0); // Single attempt per reconnection cycle
        const duration = Date.now() - startTime;
        this.outputChannel.appendLine('✅ Reconnection successful');

        // [WEEK 3] Log successful reconnection
        if (this.errorClassifier) {
          await this.errorClassifier.logTelemetry({
            type: 'reconnection',
            retryAttempt: this.reconnectAttempt,
            duration
          });
        }
      } catch (error) {
        this.outputChannel.appendLine(`Reconnection attempt failed: ${error}`);
        // Try again with next backoff
        this.attemptReconnection();
      }
    }, delay);
  }

  /**
   * [WEEK 1] Get persisted execution state from workspace
   */
  private async loadExecutionState(): Promise<Record<string, string[]>> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      return {};
    }

    const stateFilePath = path.join(workspaceFolder.uri.fsPath, '.vscode', 'mcp-state.json');

    try {
      if (fs.existsSync(stateFilePath)) {
        const stateData = fs.readFileSync(stateFilePath, 'utf-8');
        return JSON.parse(stateData);
      }
    } catch (error) {
      this.outputChannel.appendLine(`Failed to load execution state: ${error}`);
    }

    return {};
  }

  /**
   * [WEEK 1] Save execution state to workspace
   */
  private async saveExecutionState(notebookPath: string, completedCellIds: string[]): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      return;
    }

    const vscodeDir = path.join(workspaceFolder.uri.fsPath, '.vscode');
    const stateFilePath = path.join(vscodeDir, 'mcp-state.json');

    try {
      // Ensure .vscode directory exists
      if (!fs.existsSync(vscodeDir)) {
        fs.mkdirSync(vscodeDir, { recursive: true });
      }

      // Load existing state
      const state = await this.loadExecutionState();

      // Update with new completed cells
      state[notebookPath] = completedCellIds;

      // Save to file
      fs.writeFileSync(stateFilePath, JSON.stringify(state, null, 2), 'utf-8');
    } catch (error) {
      this.outputChannel.appendLine(`Failed to save execution state: ${error}`);
    }
  }

  /**
   * [WEEK 1] Public method to save execution state (called by kernel provider)
   */
  public async persistExecutionState(notebookPath: string, completedCellIds: string[]): Promise<void> {
    return this.saveExecutionState(notebookPath, completedCellIds);
  }

  /**
   * [WEEK 1] Public method to load execution state (called by kernel provider)
   */
  public async restoreExecutionState(): Promise<Record<string, string[]>> {
    return this.loadExecutionState();
  }

  /**
   * Handle process exit
   */
  private handleProcessExit(code: number | null, signal: NodeJS.Signals | null): void {
    this.process = undefined;

    const error = new Error(`MCP server exited unexpectedly: code=${code}, signal=${signal}`);
    this.rejectAllPending(error);

    // Auto-restart if enabled and not shutting down
    if (this.autoRestart && !this.isShuttingDown) {
      this.outputChannel.appendLine('Auto-restarting MCP server in 2 seconds...');
      setTimeout(() => {
        this.start().catch((err) => {
          this.outputChannel.appendLine(`Failed to restart server: ${err.message}`);
          vscode.window.showErrorMessage(`MCP server failed to restart: ${err.message}`);
        });
      }, 2000);
    }
  }

  /**
   * Reject all pending requests
   */
  private rejectAllPending(error: Error): void {
    for (const pending of this.pendingRequests.values()) {
      pending.reject(error);
    }
    this.pendingRequests.clear();
  }

  /**
   * Wait for server to be ready
   */
  private async waitForReady(): Promise<void> {
    // Simple readiness check: send a test request
    // The server should respond even if the tool fails
    return new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('Server startup timeout'));
      }, 30000);

      // Try to list environments as a health check
      this.callTool('list_environments', {})
        .then(() => {
          clearTimeout(timeout);
          resolve();
        })
        .catch((error) => {
          clearTimeout(timeout);
          // If the tool call fails but we got a response, server is ready
          if (error.message.includes('MCP error')) {
            resolve();
          } else {
            reject(error);
          }
        });
    });
  }

  /**
   * Find Python executable (exposed for dependency checking)
   */
  async findPythonExecutable(): Promise<string> {
    // 0. Check extension config first (explicit override)
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    const configuredPath = config.get<string>('pythonPath');
    if (configuredPath) {
      this.outputChannel.appendLine(`Using configured pythonPath: ${configuredPath}`);
      return configuredPath;
    }

    // 1. Check for local .venv in usage workspace (convenient for dev/test)
    const serverPath = this.findServerPath();
    const venvPython = process.platform === 'win32'
      ? path.join(serverPath, '.venv', 'Scripts', 'python.exe')
      : path.join(serverPath, '.venv', 'bin', 'python');

    if (require('fs').existsSync(venvPython)) {
      this.outputChannel.appendLine(`Using local .venv Python: ${venvPython}`);
      return venvPython;
    }

    // 2. Check Python extension
    try {
      const pythonExtension = vscode.extensions.getExtension('ms-python.python');
      if (pythonExtension) {
        if (!pythonExtension.isActive) {
          await pythonExtension.activate();
        }

        // Use the API properly
        // Note: The API shape depends on version, checking commonly available API
        // This is a simplified check
        const pythonApi = pythonExtension.exports;
        if (pythonApi.settings && pythonApi.settings.getExecutionDetails) {
          const details = pythonApi.settings.getExecutionDetails();
          if (details && details.execCommand && details.execCommand[0]) {
            return details.execCommand[0];
          }
        }
      }
    } catch (e) {
      console.warn("Failed to get Python API", e);
    }

    // 3. Use system Python
    return process.platform === 'win32' ? 'python' : 'python3';
  }

  /**
   * Find MCP server path.
   * Returns empty string '' if no local source found (implies installed package).
   * Priority:
   * 1. User configuration (mcp-jupyter.serverPath)
   * 2. Pip-installed package (mcp-server-jupyter)
   * 3. Bundled with extension (python_server/)
   * 4. Development sibling directory (../tools/mcp-server-jupyter)
   */
  findServerPath(): string {
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    const configuredPath = config.get<string>('serverPath');
    if (configuredPath) {
      return configuredPath;
    }

    // Check if installed via pip
    try {
      const { execSync } = require('child_process');
      const pythonPath = config.get<string>('pythonPath') || 'python3';

      // Try to find the package installation location
      const showOutput = execSync(`${pythonPath} -m pip show mcp-server-jupyter`, {
        encoding: 'utf-8',
        stdio: ['pipe', 'pipe', 'pipe']  // Suppress stderr
      });

      // Parse Location: line from pip show output
      const match = showOutput.match(/Location:\s*(.+)/i);
      if (match && match[1]) {
        const sitePackages = match[1].trim();
        const installedPath = path.join(sitePackages, 'mcp_server_jupyter');

        if (fs.existsSync(path.join(installedPath, 'src', 'main.py'))) {
          this.outputChannel.appendLine(`Found pip-installed server at: ${installedPath}`);
          return installedPath;
        }
      }
    } catch (error) {
      // pip show failed - package not installed, continue to fallbacks
    }

    // When packaged, Python server is bundled in extension root at python_server/
    // When in development, look for sibling directory
    const extensionPath = path.dirname(path.dirname(__dirname));  // out/src/ -> vscode-extension/

    // Try bundled location first (production)
    const bundledPath = path.join(extensionPath, 'python_server');
    if (require('fs').existsSync(path.join(bundledPath, 'src', 'main.py'))) {
      return bundledPath;
    }

    // Fall back to development location
    const devPath = path.join(extensionPath, '..', 'tools', 'mcp-server-jupyter');
    if (require('fs').existsSync(path.join(devPath, 'src', 'main.py'))) {
      return devPath;
    }

    // Fallback: Return empty string.
    // This tells start() to assume the package is installed in the python environment.
    return '';
  }

  /**
   * Install a package
   */
  async installPackage(notebookPath: string, packageSpec: string): Promise<{ success: boolean; message?: string, requires_restart?: boolean }> {
    const result = await this.callTool('install_package', {
      notebook_path: notebookPath,
      package: packageSpec,
    });

    // Handle JSON result
    // Normalize ToolResult (which comes as {success: bool, data: {...}, ...})
    // If successful, data contains requires_restart
    let normalized: any = null;

    if (typeof result === 'string') {
      try {
        normalized = JSON.parse(result);
      } catch {
        // fallback
      }
    } else {
      normalized = result;
    }

    if (normalized && typeof normalized === 'object') {
      const data = normalized.data || {};

      // [HIDDEN DEPENDENCY TRAP] Check if user wants to add to requirements.txt
      if (normalized.success && data.requirements_path) {
        const reqPath = data.requirements_path;
        const pkgName = data.package || packageSpec;

        // Prompt user: "Added 'pandas' to kernel. Add to requirements.txt?"
        vscode.window.showInformationMessage(
          `Package '${pkgName}' installed. Add to requirements.txt?`,
          'Yes', 'No'
        ).then(choice => {
          if (choice === 'Yes') {
            try {
              // Read existing
              const content = fs.readFileSync(reqPath, 'utf8');
              if (!content.includes(pkgName)) {
                // Append
                const newContent = content.endsWith('\n') ? `${content}${pkgName}\n` : `${content}\n${pkgName}\n`;
                fs.writeFileSync(reqPath, newContent);
                vscode.window.showInformationMessage(`Added ${pkgName} to requirements.txt`);
              } else {
                vscode.window.showInformationMessage(`${pkgName} is already in requirements.txt`);
              }
            } catch (e) {
              vscode.window.showErrorMessage(`Failed to update requirements.txt: ${e}`);
            }
          }
        });
      }

      if (normalized.success && data.requires_restart) {
        return { success: true, requires_restart: true, message: normalized.user_message };
      }
      return { success: normalized.success, message: normalized.error_msg || normalized.user_message };
    }

    return { success: false, message: 'Unknown error' };
  }

  /**
   * Upload a local file to the kernel's workspace
   */
  async uploadFile(notebookPath: string, localFilePath: string): Promise<{ success: boolean; message?: string }> {
    try {
      const fs = require('fs');
      const path = require('path');

      const filename = path.basename(localFilePath);
      const fileContent = fs.readFileSync(localFilePath);
      const base64Content = fileContent.toString('base64');

      // Call the tool
      const result = await this.callTool('upload_file', {
        server_path: filename, // Upload to current working directory
        content_base64: base64Content
      });

      // Parse result
      let normalized: any = null;
      if (typeof result === 'string') {
        try {
          normalized = JSON.parse(result);
        } catch {
          // fallback
        }
      } else {
        normalized = result;
      }

      if (normalized) {
        if (normalized.success) {
          return { success: true, message: normalized.user_message || `Successfully uploaded ${filename}` };
        } else {
          return { success: false, message: normalized.error_msg || normalized.message || 'Upload failed' };
        }
      }
      return { success: false, message: 'Invalid tool response' };

    } catch (error) {
      return { success: false, message: `Upload error: ${error instanceof Error ? error.message : String(error)}` };
    }
  }

  /**
   * Get output channel for display
   */
  getOutputChannel(): vscode.OutputChannel {
    return this.outputChannel;
  }

  /**
   * Check if server is running
   */
  isRunning(): boolean {
    return this.process !== undefined;
  }

  /**
   * Dispose resources
   */
  dispose(): void {
    // [WEEK 1] Clean up reconnection timer and heartbeat
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopHeartbeat();

    this.outputChannel.dispose();
  }
}
