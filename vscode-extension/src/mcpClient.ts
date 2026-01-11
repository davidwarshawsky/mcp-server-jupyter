import { ChildProcess, spawn } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import * as net from 'net';
import * as vscode from 'vscode';
import WebSocket from 'ws';
import { McpRequest, McpResponse, ExecutionStatus, PythonEnvironment, NotebookOutput } from './types';

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
  private _onNotification = new vscode.EventEmitter<{ method: string, params: any }>();
  public readonly onNotification = this._onNotification.event;

  constructor() {
    this.outputChannel = vscode.window.createOutputChannel('MCP Jupyter Server');
  }

  public getStatus(): 'running' | 'stopped' | 'starting' {
    if (this.isStarting) return 'starting';
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
        
        // Connect directly without spawning
        await this.connectWebSocket(wsUrl, 5, 1000); // Fewer retries for connect mode
        
      } else {
        // Mode: Spawn new server (Default)
        const pythonPath = await this.findPythonExecutable();
        const serverPath = this.findServerPath();
        const port = await this.getFreePort();
        wsUrl = `ws://127.0.0.1:${port}/ws`;

        this.outputChannel.appendLine(`Starting MCP server (WebSocket mode)...`);
        this.outputChannel.appendLine(`Python: ${pythonPath}`);
        this.outputChannel.appendLine(`Server: ${serverPath ? serverPath : '(Installed Package)'}`);
        this.outputChannel.appendLine(`Port: ${port}`);
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
        };
        
        if (serverPath) {
             spawnOptions.cwd = serverPath;
        }

        this.process = spawn(pythonPath, ['-m', 'src.main', '--transport', 'websocket', '--port', port.toString()], spawnOptions);

        this.process.stdout?.on('data', (data) => {
          // Log stdout but don't parse it as JSON-RPC if using WebSocket
          this.outputChannel.append(`[stdout] ${data.toString()}`);
        });

        this.process.stderr?.on('data', (data) => {
          this.outputChannel.append(`[stderr] ${data.toString()}`);
        });

        this.process.on('exit', (code, signal) => {
          this.outputChannel.appendLine(`MCP server exited: code=${code}, signal=${signal}`);
          this.handleProcessExit(code, signal);
        });

        this.process.on('error', (error) => {
          this.outputChannel.appendLine(`MCP server error: ${error.message}`);
          this.rejectAllPending(new Error(`Server process error: ${error.message}`));
        });

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
    for (let i = 0; i < retries; i++) {
        try {
            await new Promise<void>((resolve, reject) => {
                this.ws = new WebSocket(url);
                
                this.ws.on('open', () => {
                    this.outputChannel.appendLine('WebSocket connected');
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

                this.ws.on('close', (code, reason) => {
                     this.outputChannel.appendLine(`WebSocket closed: ${code} ${reason}`);
                     this.ws = undefined;
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
   * Start a kernel for a notebook
   */
  async startKernel(notebookPath: string, venvPath?: string): Promise<void> {
    return this.callTool('start_kernel', {
      notebook_path: notebookPath,
      venv_path: venvPath,
    });
  }

  /**
   * Execute a cell asynchronously and return task ID
   */
  async runCellAsync(notebookPath: string, index: number, codeContent: string, taskId?: string): Promise<string> {
    const result = await this.callTool('run_cell_async', {
      notebook_path: notebookPath,
      index,
      code_override: codeContent,
      task_id_override: taskId
    });
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
    return result;
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
   * Handle a JSON-RPC response or notification
   */
  private handleResponse(response: McpResponse): void {
    // Check for Notification
    if (response.method && (response.id === undefined || response.id === null)) {
        this._onNotification.fire({ method: response.method, params: response.params });
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
    // 0. Check for local .venv in usage workspace (Priority for Hardening)
    const serverPath = this.findServerPath();
    const venvPython = process.platform === 'win32' 
        ? path.join(serverPath, '.venv', 'Scripts', 'python.exe')
        : path.join(serverPath, '.venv', 'bin', 'python');
    
    if (require('fs').existsSync(venvPython)) {
        this.outputChannel.appendLine(`Using local .venv Python: ${venvPython}`);
        return venvPython;
    }

    // 1. Check extension config
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    const configuredPath = config.get<string>('pythonPath');
    if (configuredPath) {
      return configuredPath;
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
   */
  findServerPath(): string {
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    const configuredPath = config.get<string>('serverPath');
    if (configuredPath) {
      return configuredPath;
    }

    // When packaged, Python server is bundled in extension root at python_server/
    // When in development, look for sibling directory
    const extensionPath = path.dirname(__dirname);  // out/ -> vscode-extension/
    
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
    this.outputChannel.dispose();
  }
}
