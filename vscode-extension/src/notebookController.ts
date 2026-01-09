import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { McpClient } from './mcpClient';
import { ExecutionStatus, NotebookOutput } from './types';

export class McpNotebookController {
  private controller: vscode.NotebookController;
  private mcpClient: McpClient;
  private executionQueue = new Map<string, vscode.NotebookCellExecution>();
  private activeTaskIds = new Map<string, string>(); // execution key -> MCP task ID
  private notebookKernels = new Map<string, boolean>(); // track which notebooks have started kernels
  private kernelStartPromises = new Map<string, Promise<void>>(); // track in-progress kernel starts
  private statusBar: vscode.StatusBarItem;
  private currentEnvironment?: { name: string; path: string; type: string };

  constructor(mcpClient: McpClient) {
    this.mcpClient = mcpClient;

    this.controller = vscode.notebooks.createNotebookController(
      'mcp-agent-kernel',
      'jupyter-notebook',
      '🤖 MCP Agent Kernel'
    );

    this.controller.supportedLanguages = ['python'];
    this.controller.supportsExecutionOrder = true;
    this.controller.executeHandler = this.executeHandler.bind(this);
    this.controller.interruptHandler = this.interruptHandler.bind(this);

    // Create status bar item
    this.statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    this.statusBar.command = 'mcp-jupyter.selectEnvironment';
    this.statusBar.tooltip = 'Click to change Python environment';
    this.updateStatusBar();
    this.statusBar.show();
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

      // Start async execution
      const taskId = await this.mcpClient.runCellAsync(
        notebook.uri.fsPath,
        cell.index
      );

      // Track task ID for interrupt capability
      this.activeTaskIds.set(executionKey, taskId);

      // Stream outputs using incremental polling
      const pollingInterval = vscode.workspace
        .getConfiguration('mcp-jupyter')
        .get<number>('pollingInterval', 500);

      let outputIndex = 0;
      let currentOutputs: vscode.NotebookCellOutput[] = [];
      let isComplete = false;

      while (!isComplete) {
        await this.sleep(pollingInterval);
        
        // Get only new outputs since last check
        const stream = await this.mcpClient.getExecutionStream(
          notebook.uri.fsPath,
          taskId,
          outputIndex
        );

        // Append new outputs incrementally
        if (stream.new_outputs && stream.new_outputs.length > 0) {
          const newCellOutputs = stream.new_outputs.map((output) => this.convertOutput(output));
          currentOutputs.push(...newCellOutputs);
          await execution.replaceOutput(currentOutputs);
          outputIndex = stream.next_index;
        }

        // Set execution count when available
        if (stream.execution_count !== undefined) {
          execution.executionOrder = stream.execution_count;
        }

      // Check completion status
      if (stream.status === 'completed') {
        // Add execution metadata to cell
        await this.addExecutionMetadata(cell, 'human', Date.now());
        execution.end(true, Date.now());
        isComplete = true;
      } else if (stream.status === 'error') {
        execution.end(false, Date.now());
        isComplete = true;
      } else if (stream.status !== 'queued' && stream.status !== 'running') {
        // Unknown status, treat as completion
        execution.end(false, Date.now());
        isComplete = true;
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
   * Actually start the kernel (called by ensureKernelStarted with locking)
   */
  private async doStartKernel(notebook: vscode.NotebookDocument): Promise<void> {
    const notebookPath = notebook.uri.fsPath;

    // Check if we need to sync state from disk (handoff protocol)
    try {
      const syncNeeded = await this.mcpClient.detectSyncNeeded(notebookPath);
      if (syncNeeded) {
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
    } catch (error) {
      // Sync detection failed, continue with normal startup
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

    // Watch for notebook close to stop kernel
    const disposable = vscode.workspace.onDidCloseNotebookDocument(async (closed) => {
      if (closed.uri.fsPath === notebookPath) {
        await this.mcpClient.stopKernel(notebookPath);
        this.notebookKernels.delete(notebookPath);
        disposable.dispose();
      }
    });
  }

  /**
   * Convert MCP output to VSCode NotebookCellOutput
   */
  private convertOutput(output: NotebookOutput): vscode.NotebookCellOutput {
    switch (output.output_type) {
      case 'stream':
        return new vscode.NotebookCellOutput([
          vscode.NotebookCellOutputItem.stdout(this.normalizeText(output.text)),
        ]);

      case 'execute_result':
      case 'display_data':
        return this.convertDisplayData(output);

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
  private convertDisplayData(output: NotebookOutput): vscode.NotebookCellOutput {
    const items: vscode.NotebookCellOutputItem[] = [];

    if (output.data) {
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
            
            // Check if data is a file path (e.g., "assets/plot_123.png")
            if (dataStr.startsWith('assets/') || dataStr.startsWith('./assets/')) {
              try {
                // Get MCP server directory from config or use relative path
                const config = vscode.workspace.getConfiguration('mcp-jupyter');
                const serverPath = config.get<string>('serverPath') || 
                  path.join(path.dirname(__dirname), '..', 'tools', 'mcp-server-jupyter');
                
                const assetPath = path.isAbsolute(dataStr) ? dataStr : path.join(serverPath, dataStr);
                
                if (fs.existsSync(assetPath)) {
                  buffer = fs.readFileSync(assetPath);
                } else {
                  // File doesn't exist, show error
                  items.push(vscode.NotebookCellOutputItem.text(
                    `⚠️ Asset file not found: ${dataStr}`,
                    'text/plain'
                  ));
                  continue;
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
  updateEnvironment(env: { name: string; path: string; type: string }): void {
    this.currentEnvironment = env;
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
   * Dispose controller
   */
  dispose(): void {
    this.controller.dispose();
    this.statusBar.dispose();
  }
}
