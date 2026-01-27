import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as crypto from 'crypto';
import { MCPClient } from './mcpClient';
import { VariableDashboardProvider } from './variableDashboard';
import { ExecutionStatus, NotebookOutput } from './types';

export class McpNotebookController {
  private controller: vscode.NotebookController;
  private mcpClient: MCPClient;
  private variableDashboard?: VariableDashboardProvider;
  private executionQueue = new Map<string, vscode.NotebookCellExecution>();
  private activeTaskIds = new Map<string, string>(); // execution key -> MCP task ID
  private notebookKernels = new Map<string, boolean>(); // track which notebooks have started kernels
  private kernelStartPromises = new Map<string, Promise<void>>(); // track in-progress kernel starts
  private completionResolvers = new Map<string, (success: boolean) => void>();
  private activeExecutions = new Map<string, vscode.NotebookCellExecution>(); // taskId -> execution
  private kernelMsgIdToExecution = new Map<string, vscode.NotebookCellExecution>(); // kernel msg_id -> execution
  private statusBar: vscode.StatusBarItem;
  private currentEnvironment?: { name: string; path: string; type: 'venv' | 'conda' | 'global' };

  // [WEEK 1] Track completed cells per notebook for state persistence
  private completedCells = new Map<string, Set<string>>();

  constructor(mcpClient: MCPClient) {
    this.mcpClient = mcpClient;

    // Subscribe to MCP notifications (Event-Driven Architecture)
    this.mcpClient.onNotification(event => this.handleNotification(event));

    this.controller = vscode.notebooks.createNotebookController(
      'mcp-agent-kernel',
      'jupyter-notebook',
      '🤖 MCP Agent Kernel'
    );

    this.controller.supportedLanguages = ['python'];
    this.controller.supportsExecutionOrder = true;
    this.controller.executeHandler = this.executeHandler.bind(this);
    this.controller.interruptHandler = this.interruptHandler.bind(this);

    // [WEEK 1] Restore execution state on startup
    this.restoreExecutionState();

    // Create status bar item
    this.statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    this.statusBar.command = 'mcp-jupyter.selectEnvironment';
    this.statusBar.tooltip = 'Click to change Python environment';
    this.updateStatusBar();
    this.statusBar.show();
  }

  /**
   * Set variable dashboard instance (called by extension.ts)
   */
  setVariableDashboard(dashboard: VariableDashboardProvider): void {
    this.variableDashboard = dashboard;
  }

  /**
   * Handle incoming MCP notifications
   */
  private async handleNotification(event: { method: string, params: any }): Promise<void> {
    // 1. Handle Execution Started (Bind the IDs)
    if (event.method === 'notebook/cell_execution_started') {
      const { exec_id, kernel_msg_id } = event.params;
      const execution = this.activeExecutions.get(exec_id);
      if (execution) {
        // Map the Kernel's ID to our Active Execution
        this.kernelMsgIdToExecution.set(kernel_msg_id, execution);
      }
    }

    // 2. Handle Raw IOPub Messages (The New Protocol)
    else if (event.method === 'notebook/iopub_message') {
      const params = event.params;
      const msgId = params.parent_header?.msg_id;

      // Lookup the execution using the Kernel ID we bound earlier
      const execution = this.kernelMsgIdToExecution.get(msgId);

      if (execution) {
        await this.processIOPubMessage(execution, params);
      }
    }

    // Legacy handling for backward compatibility
    else if (event.method === 'notebook/output') {
      const { exec_id, type, content } = event.params;
      const execution = this.activeExecutions.get(exec_id);

      if (execution) {
        let output: NotebookOutput | undefined;

        if (type === 'stream') {
          output = { output_type: 'stream', name: content.name, text: content.text };
        } else if (type === 'display_data') {
          output = { output_type: 'display_data', data: content.data, metadata: content.metadata };
        } else if (type === 'execute_result') {
          output = { output_type: 'execute_result', data: content.data, metadata: content.metadata, execution_count: content.execution_count };
          if (content.execution_count) {
            execution.executionOrder = content.execution_count;
          }
        } else if (type === 'error') {
          output = { output_type: 'error', ename: content.ename, evalue: content.evalue, traceback: content.traceback };
        }

        if (output) {
          // Get notebook for asset path resolution
          const notebooks = vscode.workspace.notebookDocuments;
          let targetNotebook: vscode.NotebookDocument | undefined;
          
          // Try to match notebook by comparing execution context
          const config = vscode.workspace.getConfiguration('mcp-jupyter');
          const serverPath = config.get<string>('serverPath') || '';
          
          for (const nb of notebooks) {
            const notebookDir = path.dirname(nb.uri.fsPath);
            // Check if this notebook's directory matches the expected execution context
            if (serverPath.includes(notebookDir) || notebookDir === serverPath) {
              targetNotebook = nb;
              break;
            }
          }
          
          const cellOutput = await this.convertOutput(output, targetNotebook);
          await execution.appendOutput([cellOutput]);
        }
      }
    } else if (event.method === 'notebook/status') {
      const { exec_id, status } = event.params;
      const resolver = this.completionResolvers.get(exec_id);

      if (resolver) {
        if (status === 'completed') {
          resolver(true);
        } else if (status === 'error' || status === 'cancelled') {
          resolver(false);
        }

        if (status !== 'running' && status !== 'queued') {
          this.completionResolvers.delete(exec_id);
        }
      }
    } else if (event.method === 'notebook/input_request') {
      const { notebook_path, prompt, password, secret_key } = event.params;

      // [MONTH 4 FIX] Secret Injection Interceptor
      if (secret_key) {
        const secretValue = await vscode.window.showInputBox({
            title: `🔐 Agent Requests Secret: ${secret_key}`,
            prompt: prompt || `Please enter value for ${secret_key}. It will be injected into os.environ temporarily.`,
            password: true, // Mask input
            ignoreFocusOut: true,
            placeHolder: `Value for ${secret_key}`
        });

        if (secretValue) {
            // Send back. The server-side request_secret tool should be waiting for this input.
            await this.mcpClient.submitInput(notebook_path, secretValue);
            // Avoid logging secret; show minimal confirmation to user
            vscode.window.showInformationMessage(`Secret '${secret_key}' injected securely.`);
        } else {
            // User cancelled - abort the tool call on server side to avoid leaving secrets or hanging state.
            await this.mcpClient.cancelExecution(notebook_path);
        }
        return;
      }

      // Existing standard input logic...

      const value = await vscode.window.showInputBox({
        prompt: prompt || 'Input requested by kernel',
        password: password === true,
        ignoreFocusOut: true,
        placeHolder: 'Enter value for input() request'
      });

      // Submit back to kernel
      await this.mcpClient.submitInput(notebook_path, value || '');
    } else if (event.method === 'internal/reconnected') {
      // WebSocket reconnected: reconcile any executions that the client
      // believes are running. This helps recover cases where the server
      // broadcast a 'completed' event while the client was disconnected.
      const tasksByNotebook = new Map<string, string[]>();
      for (const [key, taskId] of this.activeTaskIds.entries()) {
        const nbPath = key.split(':')[0];
        const arr = tasksByNotebook.get(nbPath) || [];
        arr.push(taskId);
        tasksByNotebook.set(nbPath, arr);
      }

      for (const [nbPath, ids] of tasksByNotebook.entries()) {
        try {
          await this.mcpClient.reconcileExecutions(ids, nbPath);
        } catch (e) {
          console.error('Failed to reconcile executions on reconnect:', e);
        }
      }
    }
  }

  /**
   * New Helper: Parse Raw Jupyter Messages -> VS Code Outputs
   */
  private async processIOPubMessage(execution: vscode.NotebookCellExecution, msg: any) {
    const content = msg.content;

    try {
      switch (msg.msg_type) {
        case 'stream':
          await execution.appendOutput(new vscode.NotebookCellOutput([
            vscode.NotebookCellOutputItem.text(content.text, 'text/plain') // Handle stdout/stderr
          ]));
          break;

        case 'display_data':
        case 'execute_result':
          const items: vscode.NotebookCellOutputItem[] = [];
          // Convert Jupyter mime bundle to VS Code Items
          for (const [mime, data] of Object.entries(content.data || {})) {
            if (typeof data === 'string') {
              // Handle Base64 images vs Plain Text
              if (mime.startsWith('image/')) {
                items.push(new vscode.NotebookCellOutputItem(Buffer.from(data, 'base64'), mime));
              } else {
                items.push(vscode.NotebookCellOutputItem.text(data, mime));
              }
            } else {
              // JSON objects
              items.push(vscode.NotebookCellOutputItem.json(data, mime));
            }
          }
          await execution.appendOutput(new vscode.NotebookCellOutput(items, content.metadata || {}));
          break;

        case 'error':
          await execution.appendOutput(new vscode.NotebookCellOutput([
            vscode.NotebookCellOutputItem.error({
              name: content.ename,
              message: content.evalue,
              stack: content.traceback?.join('\n') || ''
            })
          ]));
          break;

        case 'status':
          if (content.execution_state === 'idle') {
            // Cleanup
            execution.end(true, Date.now());
            this.kernelMsgIdToExecution.delete(msg.parent_header?.msg_id);
          }
          break;
      }
    } catch (e) {
      console.error("Failed to process IOPub message", e);
    }
  }

  /**
   * Execute notebook cells
   */
  private async executeHandler(
    cells: vscode.NotebookCell[],
    notebook: vscode.NotebookDocument,
    controller: vscode.NotebookController
  ): Promise<void> {
    for (const cell of cells) {
      await this.executeCell(cell, notebook);
    }
  }

  /**
   * Execute a single cell
   */
  private async executeCell(
    cell: vscode.NotebookCell,
    notebook: vscode.NotebookDocument
  ): Promise<void> {
    const execution = this.controller.createNotebookCellExecution(cell);
    execution.start(Date.now());

    const executionKey = `${notebook.uri.fsPath}:${cell.index}`;
    this.executionQueue.set(executionKey, execution);

    try {
      // Ensure kernel is started for this notebook
      await this.ensureKernelStarted(notebook);

      // Clear previous outputs
      execution.clearOutput();

      // Generate ID client-side to prevent race conditions
      const taskId = crypto.randomUUID();

      // Track task ID for interrupt capability
      this.activeTaskIds.set(executionKey, taskId);
      this.activeExecutions.set(taskId, execution);

      // Create a promise that resolves when execution completes (via Notification)
      const completionPromise = new Promise<boolean>((resolve) => {
        this.completionResolvers.set(taskId, resolve);
      });

      // Start resource polling
      const resourceTimer = setInterval(async () => {
        try {
          const stats = await this.mcpClient.checkKernelResources(notebook.uri.fsPath);
          this.statusBar.text = `$(pulse) Running (CPU: ${stats.cpu_percent}%, RAM: ${Math.round(stats.memory_mb)}MB)`;
          this.statusBar.show();
        } catch (e) {
          // Ignore polling errors
        }
      }, 5000);

      // Start async execution with explicit ID
      // Suspend variable polling while kernel is busy
      if (this.variableDashboard) {
        this.variableDashboard.setBusy(true);
      }
      await this.mcpClient.runCellAsync(
        notebook.uri.fsPath,
        cell.index,
        cell.document.getText(),
        taskId
      );

      // SAFETY TIMEOUT: Don't let the UI hang forever
      const timeoutPromise = new Promise<boolean>((_, reject) => {
        // 10 minutes hard timeout (adjust based on config)
        setTimeout(() => reject(new Error("Execution timed out (Client Safety Limit)")), 600000);
      });

      // Wait for completion (Event-Driven) or safety timeout
      try {
        const success = await Promise.race([completionPromise, timeoutPromise]);

        if (success) {
          await this.addExecutionMetadata(cell, 'human', Date.now());

          // [WEEK 1] Track completed cell and persist state
          const notebookPath = notebook.uri.fsPath;
          if (!this.completedCells.has(notebookPath)) {
            this.completedCells.set(notebookPath, new Set());
          }
          this.completedCells.get(notebookPath)!.add(`cell-${cell.index}`);

          // Persist to disk (fire-and-forget)
          const completedCellIds = Array.from(this.completedCells.get(notebookPath)!);
          this.mcpClient.persistExecutionState(notebookPath, completedCellIds)
            .catch(err => console.error('Failed to persist execution state:', err));

          execution.end(true, Date.now());
        } else {
          execution.end(false, Date.now());
        }
      } catch (error) {
        // Handle timeout or other errors
        const msg = error instanceof Error ? error.message : String(error);

        // [FIX START] Kill the zombie process on client-side timeout: send
        // a cancel request to the server to make sure the kernel does not
        // keep executing the timed-out task in the background.
        try {
          console.warn(`Execution timed out locally. Sending cancel signal for ${taskId}`);
          // Fire-and-forget: we don't want this to block UI cleanup
          this.mcpClient.cancelExecution(notebook.uri.fsPath, taskId).catch(e => console.error("Failed to cancel zombie task:", e));
        } catch (e) {
          console.error('Failed to invoke cancelExecution:', e);
        }
        // [FIX END]

        await execution.replaceOutput([
          new vscode.NotebookCellOutput([
            vscode.NotebookCellOutputItem.error({ name: 'TimeoutError', message: msg })
          ])
        ]);
        execution.end(false, Date.now());
      } finally {
        clearInterval(resourceTimer);
        this.updateStatusBar(); // Reset status bar
        this.completionResolvers.delete(taskId);
        // Resume variable polling when kernel returns to idle
        if (this.variableDashboard) {
          this.variableDashboard.setBusy(false);
        }
      }

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      await execution.replaceOutput([
        new vscode.NotebookCellOutput([
          vscode.NotebookCellOutputItem.error({
            name: 'ExecutionError',
            message: errorMessage,
          }),
        ]),
      ]);
      execution.end(false, Date.now());
    } finally {
      this.executionQueue.delete(executionKey);
      this.activeTaskIds.delete(executionKey);
    }
  }

  /**
   * Interrupt cell execution
   */
  private async interruptHandler(notebook: vscode.NotebookDocument): Promise<void> {
    const notebookPath = notebook.uri.fsPath;

    try {
      // Interrupt kernel via MCP
      await this.mcpClient.cancelExecution(notebookPath);

      // Clean up local state
      for (const [key, execution] of this.executionQueue.entries()) {
        if (key.startsWith(notebookPath)) {
          execution.end(false, Date.now());
          this.executionQueue.delete(key);
          this.activeTaskIds.delete(key);
        }
      }

      vscode.window.showInformationMessage('Cell execution interrupted');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      vscode.window.showErrorMessage(`Failed to interrupt: ${errorMessage}`);
    }
  }

  /**
   * Ensure kernel is started for notebook
   */
  private async ensureKernelStarted(notebook: vscode.NotebookDocument): Promise<void> {
    const notebookPath = notebook.uri.fsPath;

    // If kernel already started, return immediately
    if (this.notebookKernels.has(notebookPath)) {
      return;
    }

    // If another call is already starting the kernel, wait for it
    const existingPromise = this.kernelStartPromises.get(notebookPath);
    if (existingPromise) {
      return existingPromise;
    }

    // [SESSION DISCOVERY] Check if server has an active session before starting
    try {
      const sessionCheck = await this.mcpClient.callTool('find_active_session', {
        notebook_path: notebookPath
      });

      const sessionInfo = JSON.parse(sessionCheck.content[0].text);

      if (sessionInfo.found && sessionInfo.status === 'running') {
        const startTime = new Date(sessionInfo.start_time).toLocaleString();

        // Prompt user: Resume or Start Fresh?
        const choice = await vscode.window.showInformationMessage(
          `Found active kernel for this notebook (Started: ${startTime}). Resume session?`,
          '✅ Resume Session',
          '🔄 Start Fresh (Restart)'
        );

        if (choice === '✅ Resume Session') {
          // Just connect to existing kernel, don't restart
          vscode.window.showInformationMessage('Resuming existing session...');
          this.notebookKernels.set(notebookPath, true); // Mark as "started" (attached)
          
          // [REHYDRATION] Refresh variables immediately
          this.variableDashboard?.refresh();
          
          // [REHYDRATION] Optionally fetch execution history
          try {
            const histRes = await this.mcpClient.callTool('get_execution_history', {
              notebook_path: notebookPath
            });
            const history = JSON.parse(histRes.content[0].text);
            // Could use this to show user a summary of what happened
            if (history.length > 0) {
              const lastExecution = history[0];
              vscode.window.showInformationMessage(
                `Last execution: Cell ${lastExecution.cell_index} - ${lastExecution.status}`
              );
            }
          } catch (e) {
            // Silently fail - history is optional
            console.warn('Failed to fetch execution history:', e);
          }
          
          // [OUTPUT REHYDRATION] Restore cell outputs from persistence
          await this.rehydrateNotebookOutputs(notebook);
          
          return;
        } else if (choice === '🔄 Start Fresh (Restart)') {
          // User wants a fresh kernel - kill the old one
          try {
            await this.mcpClient.stopKernel(notebookPath);
          } catch (e) {
            console.warn('Failed to stop old kernel:', e);
          }
          // Fall through to normal startup
        } else {
          // User cancelled - don't start anything
          return;
        }
      }
    } catch (e) {
      // Fallback: If check fails, just try starting normally
      console.warn('Failed to check existing session:', e);
    }

    // Start kernel and track the promise
    const startPromise = this.doStartKernel(notebook);
    this.kernelStartPromises.set(notebookPath, startPromise);

    try {
      await startPromise;
    } finally {
      this.kernelStartPromises.delete(notebookPath);
    }
  }

  /**
   * [OUTPUT REHYDRATION] Restore cell outputs from persistence.
   * 
   * When user resumes a session, VS Code has cleared the cell outputs.
   * This method retrieves the persisted outputs from the server and
   * re-populates the notebook UI so it matches the kernel state.
   */
  private async rehydrateNotebookOutputs(notebook: vscode.NotebookDocument): Promise<void> {
    try {
      const nbPath = notebook.uri.fsPath;
      
      // Fetch full notebook history with outputs
      const historyRes = await this.mcpClient.callTool('get_notebook_history', {
        notebook_path: nbPath
      });
      
      const historyText = historyRes.content[0].text;
      const history = JSON.parse(historyText);
      
      if (!history || history.length === 0) {
        console.log('[REHYDRATE] No history to restore');
        return;
      }
      
      console.log(`[REHYDRATE] Restoring ${history.length} cell outputs for ${path.basename(nbPath)}`);
      
      // Process each cell with output history
      for (const entry of history) {
        const cellIndex = entry.cell_index;
        if (cellIndex >= notebook.cellCount) {
          continue; // Cell may have been deleted
        }
        
        const cell = notebook.cellAt(cellIndex);
        if (cell.kind !== vscode.NotebookCellKind.Code) {
          continue; // Only code cells have outputs
        }
        
        try {
          // Reconstruct VS Code NotebookCellOutput from Jupyter format
          const outputs: vscode.NotebookCellOutput[] = [];
          
          if (entry.outputs && Array.isArray(entry.outputs)) {
            for (const jupyterOutput of entry.outputs) {
              const items: vscode.NotebookCellOutputItem[] = [];
              
              // Handle different output types
              if (jupyterOutput.output_type === 'stream') {
                // Stream output (stdout/stderr)
                const text = Array.isArray(jupyterOutput.text) 
                  ? jupyterOutput.text.join('') 
                  : jupyterOutput.text;
                items.push(
                  new vscode.NotebookCellOutputItem(Buffer.from(text), 'text/plain')
                );
              } else if (jupyterOutput.output_type === 'execute_result' || jupyterOutput.output_type === 'display_data') {
                // Rich media output (plots, tables, etc.)
                const data = jupyterOutput.data || {};
                
                // Keep interactive MIME types (don't convert to PNG)
                const preferredMimes = [
                  'application/vnd.plotly.v1+json',
                  'application/vnd.vega.v5+json',
                  'text/html',
                  'text/markdown',
                  'image/png',
                  'image/jpeg',
                  'text/plain'
                ];
                
                for (const mime of preferredMimes) {
                  if (mime in data) {
                    const content = (data as any)[mime];
                    const contentStr = typeof content === 'string' 
                      ? content 
                      : JSON.stringify(content);
                    items.push(
                      new vscode.NotebookCellOutputItem(Buffer.from(contentStr), mime)
                    );
                    break; // Use first matching MIME
                  }
                }
              } else if (jupyterOutput.output_type === 'error') {
                // Error output
                const traceback = jupyterOutput.traceback || [];
                const text = traceback.join('\n');
                items.push(
                  new vscode.NotebookCellOutputItem(Buffer.from(text), 'text/plain')
                );
              }
              
              if (items.length > 0) {
                outputs.push(new vscode.NotebookCellOutput(items));
              }
            }
          }
          
          // Apply outputs to cell
          if (outputs.length > 0) {
            const edit = new vscode.WorkspaceEdit();
            const nbEdit = vscode.NotebookEdit.replaceOutput(cellIndex, outputs);
            edit.set(notebook.uri, [nbEdit]);
            await vscode.workspace.applyEdit(edit);
            
            // Set execution order if available
            if (entry.execution_count !== null && entry.execution_count !== undefined) {
              const nbEdit2 = vscode.NotebookEdit.updateCellMetadata(
                cellIndex,
                { custom: { executionCount: entry.execution_count } }
              );
              const edit2 = new vscode.WorkspaceEdit();
              edit2.set(notebook.uri, [nbEdit2]);
              await vscode.workspace.applyEdit(edit2);
            }
          }
        } catch (e) {
          console.warn(`[REHYDRATE] Failed to restore cell ${cellIndex}:`, e);
          continue;
        }
      }
      
      console.log('[REHYDRATE] Cell outputs restored successfully');
    } catch (e) {
      console.warn('[REHYDRATE] Failed to restore notebook outputs:', e);
      // Non-critical - don't fail the reconnect
    }
  }

  /**
   * Actually start the kernel (called by ensureKernelStarted with locking)
   */
  private async doStartKernel(notebook: vscode.NotebookDocument): Promise<void> {
    const notebookPath = notebook.uri.fsPath;

    // Check if we need to sync state from disk (handoff protocol)
    try {
      const syncResult = await this.mcpClient.detectSyncNeeded(notebookPath);
      let syncNeeded = false;
      let reason = '';

      if (typeof syncResult === 'boolean') {
        syncNeeded = syncResult;
      } else if (typeof syncResult === 'string') {
        const parsed = JSON.parse(syncResult);
        syncNeeded = parsed.sync_needed;
        reason = parsed.reason;
      } else {
        syncNeeded = syncResult.sync_needed;
        reason = syncResult.reason;
      }

      // If no kernel is active, we don't need to ask user to sync, we just start fresh
      if (syncNeeded && reason === 'no_active_kernel') {
        syncNeeded = false;
      }

      if (syncNeeded) {
        const selection = await vscode.window.showWarningMessage(
          "Notebook State Sync Required: The Agent's kernel state is older than the disk/buffer.",
          "Sync State Now",
          "Ignore"
        );

        if (selection === "Sync State Now") {
          await vscode.window.withProgress(
            {
              location: vscode.ProgressLocation.Notification,
              title: 'Syncing notebook state...',
              cancellable: false,
            },
            async () => {
              await this.mcpClient.syncStateFromDisk(notebookPath);
            }
          );
        }
      }
    } catch (error) {
      // Sync detection failed, but we shouldn't block startup
      console.warn('Failed to detect sync:', error);
    }

    // Start kernel
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Starting kernel...',
        cancellable: false,
      },
      async () => {
        // Check if notebook has saved environment preference
        let venvPath: string | undefined;
        const metadata = notebook.metadata as any;

        if (metadata && metadata['mcp-jupyter']?.environment) {
          const savedEnv = metadata['mcp-jupyter'].environment;
          venvPath = savedEnv.path;

          // Update status bar with saved environment
          this.currentEnvironment = {
            name: savedEnv.name,
            path: savedEnv.path,
            type: savedEnv.type,
          };
          this.updateStatusBar();
        }

        await this.mcpClient.startKernel(notebookPath, venvPath);
      }
    );

    this.notebookKernels.set(notebookPath, true);

    // Start variable dashboard polling
    if (this.variableDashboard) {
      this.variableDashboard.startPolling(notebookPath);
    }

    // Watch for notebook close to stop kernel
    const disposable = vscode.workspace.onDidCloseNotebookDocument(async (closed) => {
      if (closed.uri.fsPath === notebookPath) {
        // Stop variable dashboard polling
        if (this.variableDashboard) {
          this.variableDashboard.stopPolling();
        }

        await this.mcpClient.stopKernel(notebookPath);
        this.notebookKernels.delete(notebookPath);
        disposable.dispose();
      }
    });
  }

  /**
   * Convert MCP output to VSCode NotebookCellOutput
   */
  private async convertOutput(output: NotebookOutput, notebook?: vscode.NotebookDocument): Promise<vscode.NotebookCellOutput> {
    switch (output.output_type) {
      case 'stream':
        return new vscode.NotebookCellOutput([
          vscode.NotebookCellOutputItem.stdout(this.normalizeText(output.text)),
        ]);

      case 'execute_result':
      case 'display_data':
        return await this.convertDisplayData(output, notebook);

      case 'error':
        return new vscode.NotebookCellOutput([
          vscode.NotebookCellOutputItem.error({
            name: output.ename || 'Error',
            message: output.evalue || '',
            stack: output.traceback?.join('\n'),
          }),
        ]);

      default:
        return new vscode.NotebookCellOutput([
          vscode.NotebookCellOutputItem.text(JSON.stringify(output, null, 2)),
        ]);
    }
  }

  /**
   * Convert display data to VSCode output
   */
  private async convertDisplayData(output: NotebookOutput, notebook?: vscode.NotebookDocument): Promise<vscode.NotebookCellOutput> {
    const items: vscode.NotebookCellOutputItem[] = [];

    if (output.data) {
      // [UX] Handle custom asset MIME type for inline rendering
      if (output.data['application/vnd.mcp.asset+json']) {
        items.push(vscode.NotebookCellOutputItem.json(
          output.data['application/vnd.mcp.asset+json'],
          'application/vnd.mcp.asset+json'
        ));
        // Return early, as this is the preferred representation
        return new vscode.NotebookCellOutput(items, output.metadata);
      }

      // Phase 2: Rich Visualization Support
      // Prioritize interactive types (Plotly, Widgets)
      if (output.data['application/vnd.plotly.v1+json']) {
        items.push(vscode.NotebookCellOutputItem.json(
          output.data['application/vnd.plotly.v1+json'],
          'application/vnd.plotly.v1+json'
        ));
      }
      if (output.data['application/vnd.jupyter.widget-view+json']) {
        items.push(vscode.NotebookCellOutputItem.json(
          output.data['application/vnd.jupyter.widget-view+json'],
          'application/vnd.jupyter.widget-view+json'
        ));
      }

      // Handle different MIME types
      for (const [mimeType, data] of Object.entries(output.data)) {
        try {
          if (mimeType === 'text/plain') {
            items.push(vscode.NotebookCellOutputItem.text(this.normalizeText(data)));
          } else if (mimeType === 'text/html') {
            items.push(vscode.NotebookCellOutputItem.text(this.normalizeText(data), 'text/html'));
          } else if (mimeType === 'image/png' || mimeType === 'image/jpeg' || mimeType === 'image/svg+xml') {
            let buffer: Buffer;
            const dataStr = this.normalizeText(data);
            // NORMALIZE SLASHES: Handle Windows paths coming from Python or user input
            const dataStrNormalized = dataStr.replace(/\\/g, '/');

            // Check if data is a file path (e.g., "assets/plot_123.png")
            if (dataStrNormalized.startsWith('assets/') || dataStrNormalized.startsWith('./assets/')) {
              try {
                // [FIX: BROKEN IMAGE ICON]
                // 1. Resolve assets relative to the NOTEBOOK file, not workspace root
                let bufferPromise: Promise<Buffer> | null = null;
                let assetPath: string | null = null;

                if (notebook) {
                  // Preferred: Use notebook's directory for resolving relative asset paths
                  const notebookDir = path.dirname(notebook.uri.fsPath);
                  assetPath = path.join(notebookDir, dataStrNormalized);
                  if (fs.existsSync(assetPath)) {
                    bufferPromise = fs.promises.readFile(assetPath).then(b => Buffer.from(b));
                  }
                }

                // Fallback: Try workspace folder if notebook resolution failed
                if (!bufferPromise && !path.isAbsolute(dataStr)) {
                  const workspaceFolders = vscode.workspace.workspaceFolders;
                  if (workspaceFolders && workspaceFolders.length > 0) {
                    const notebookDir = workspaceFolders[0].uri.fsPath;
                    assetPath = path.join(notebookDir, dataStrNormalized);
                    if (fs.existsSync(assetPath)) {
                      bufferPromise = fs.promises.readFile(assetPath).then(b => Buffer.from(b));
                    }
                  }
                }

                // If we're in connect (remote) mode, fetch the asset via the server tool
                const config = vscode.workspace.getConfiguration('mcp-jupyter');
                const serverMode = config.get<string>('serverMode');

                if (serverMode === 'connect') {
                  try {
                    const assetData = await this.mcpClient.getAssetContent(dataStrNormalized);
                    const b64 = typeof assetData === 'string' ? JSON.parse(assetData).data : assetData.data;
                    buffer = Buffer.from(b64, 'base64');
                  } catch (e) {
                    items.push(vscode.NotebookCellOutputItem.text(`Remote asset load failed: ${e}`, 'text/plain'));
                    continue;
                  }
                } else {
                  // Local mode: either use workspace-resolved path or fallback to configured serverPath
                  if (!bufferPromise) {
                    const serverPath = config.get<string>('serverPath') || '';
                    const assetPath = path.join(serverPath, dataStrNormalized);
                    if (fs.existsSync(assetPath)) {
                      buffer = fs.readFileSync(assetPath);
                    } else {
                      items.push(vscode.NotebookCellOutputItem.text(`⚠️ Asset file not found: ${dataStr}`, 'text/plain'));
                      continue;
                    }
                  } else {
                    try {
                      buffer = await bufferPromise;
                    } catch (e) {
                      items.push(vscode.NotebookCellOutputItem.text(`⚠️ Failed to load asset: ${dataStr} - ${e}`, 'text/plain'));
                      continue;
                    }
                  }
                }
              } catch (fileError) {
                // Failed to read file, show error
                items.push(vscode.NotebookCellOutputItem.text(
                  `⚠️ Failed to load asset: ${dataStr} - ${fileError}`,
                  'text/plain'
                ));
                continue;
              }
            } else {
              // Base64 encoded image
              buffer = Buffer.from(dataStr, 'base64');
            }

            items.push(new vscode.NotebookCellOutputItem(buffer, mimeType));
          } else if (mimeType === 'application/json') {
            items.push(
              vscode.NotebookCellOutputItem.text(
                JSON.stringify(data, null, 2),
                'application/json'
              )
            );
          } else {
            // Generic data
            const text = typeof data === 'string' ? data : JSON.stringify(data);
            items.push(vscode.NotebookCellOutputItem.text(text, mimeType));
          }
        } catch (error) {
          console.error(`Failed to convert output for ${mimeType}:`, error);
        }
      }
    }

    // Fallback if no items created
    if (items.length === 0) {
      items.push(vscode.NotebookCellOutputItem.text(JSON.stringify(output, null, 2)));
    }

    return new vscode.NotebookCellOutput(items);
  }

  /**
   * Normalize text from string or string array
   */
  private normalizeText(text: string | string[] | any): string {
    if (Array.isArray(text)) {
      return text.join('');
    }
    if (typeof text === 'string') {
      return text;
    }
    return String(text);
  }

  /**
   * Sleep helper
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /**
   * Update environment (called from extension.ts)
   */
  updateEnvironment(env: { name: string; path: string; type: 'conda' | 'venv' | 'global' | string }): void {
    this.currentEnvironment = env as { name: string; path: string; type: 'conda' | 'venv' | 'global' };
    this.updateStatusBar();
  }

  /**
   * Update status bar text
   */
  private updateStatusBar(): void {
    if (this.currentEnvironment) {
      this.statusBar.text = `🐍 ${this.currentEnvironment.type}: ${this.currentEnvironment.name}`;
    } else {
      this.statusBar.text = '🐍 Python (default)';
    }
  }

  /**
   * Add execution metadata to cell
   * This helps track whether a cell was executed by human or agent
   */
  private async addExecutionMetadata(
    cell: vscode.NotebookCell,
    executedBy: 'human' | 'agent',
    timestamp: number
  ): Promise<void> {
    try {
      const edit = new vscode.WorkspaceEdit();
      const metadata = { ...cell.metadata };

      // Add mcp_execution metadata (separate from mcp_trace which is for agent executions)
      if (!metadata.mcp_execution) {
        metadata.mcp_execution = {};
      }

      metadata.mcp_execution = {
        executed_by: executedBy,
        timestamp: new Date(timestamp).toISOString(),
        extension_version: '0.1.0'
      };

      const cellMetadataEdit = vscode.NotebookEdit.updateCellMetadata(cell.index, metadata);
      edit.set(cell.notebook.uri, [cellMetadataEdit]);
      await vscode.workspace.applyEdit(edit);
    } catch (error) {
      console.error('Failed to add execution metadata:', error);
    }
  }

  /**
   * [WEEK 1] Restore execution state from persisted storage
   */
  private async restoreExecutionState(): Promise<void> {
    try {
      const state = await this.mcpClient.restoreExecutionState();

      // Load completed cells into memory
      for (const [notebookPath, cellIds] of Object.entries(state)) {
        this.completedCells.set(notebookPath, new Set(cellIds));
      }

      if (Object.keys(state).length > 0) {
        console.log(`Restored execution state for ${Object.keys(state).length} notebook(s)`);
      }
    } catch (error) {
      console.error('Failed to restore execution state:', error);
    }
  }

  /**
   * Dispose controller
   */
  dispose(): void {
    this.controller.dispose();
    this.statusBar.dispose();
  }
}
