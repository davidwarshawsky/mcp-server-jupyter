import * as vscode from 'vscode';
import * as path from 'path';
import { McpClient } from './mcpClient';
import { McpNotebookController } from './notebookController';
import { VariableDashboardProvider } from './variableDashboard';
import { checkPythonDependencies, promptInstallDependencies } from './dependencies';

let mcpClient: McpClient;
let notebookController: McpNotebookController;
let variableDashboard: VariableDashboardProvider;
let syncStatusBar: vscode.StatusBarItem;
const notebooksNeedingSync = new Set<string>();

export interface ExtensionApi {
  mcpClient: McpClient;
  notebookController: McpNotebookController;
  variableDashboard: VariableDashboardProvider;
}

export async function activate(context: vscode.ExtensionContext): Promise<ExtensionApi | void> {
  console.log('MCP Agent Kernel extension activating...');

  try {
    // Initialize MCP client
    mcpClient = new McpClient();
    
    // Get auto-restart setting
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    const autoRestart = config.get<boolean>('autoRestart', true);
    if (!autoRestart) {
      // Disable auto-restart if configured
      (mcpClient as any).autoRestart = false;
    }

    // Check Python dependencies before starting server
    const pythonPath = await mcpClient.findPythonExecutable();
    const serverPath = mcpClient.findServerPath();
    const outputChannel = mcpClient.getOutputChannel();

    const depsInstalled = await checkPythonDependencies(pythonPath, serverPath, outputChannel);
    if (!depsInstalled) {
      const installed = await promptInstallDependencies(pythonPath, serverPath, outputChannel);
      if (!installed) {
        throw new Error('Python dependencies are required. Please install them manually or restart the extension.');
      }
    }

    // Start MCP server
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Starting MCP Jupyter server...',
        cancellable: false,
      },
      async () => {
        await mcpClient.start();
      }
    );

    // Initialize notebook controller
    notebookController = new McpNotebookController(mcpClient);
    context.subscriptions.push(notebookController);

    // Initialize Variable Dashboard
    variableDashboard = new VariableDashboardProvider(mcpClient);
    const variableView = vscode.window.createTreeView('mcpVariables', {
      treeDataProvider: variableDashboard,
      showCollapseAll: false
    });
    context.subscriptions.push(variableView);

    // Pass variable dashboard to controller for lifecycle management
    notebookController.setVariableDashboard(variableDashboard);

    // Create sync status bar item
    syncStatusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
    syncStatusBar.command = 'mcp-jupyter.syncNotebook';
    syncStatusBar.tooltip = 'Click to sync notebook state from disk';
    context.subscriptions.push(syncStatusBar);

    // [GC HOOK] Trigger asset cleanup when the notebook is saved to disk.
    // The server can only see deletions/clears after Save, so this makes:
    // "Clear Output + Save" => "Delete backing assets".
    context.subscriptions.push(
      vscode.workspace.onDidSaveNotebookDocument((notebook) => {
        if (notebook.notebookType !== 'jupyter-notebook') {
          return;
        }

        // Fire-and-forget: don't block the save pipeline/UI.
        mcpClient.pruneUnusedAssets(notebook.uri.fsPath, false)
          .then(() => console.log(`[GC] Cleaned assets for ${notebook.uri.fsPath}`))
          .catch((e) => console.error('GC failed:', e));
      })
    );

    // Setup file watcher for notebook changes
    const notebookWatcher = vscode.workspace.createFileSystemWatcher('**/*.ipynb');
    
    notebookWatcher.onDidChange(async (uri) => {
      // Check if this notebook has an active kernel
      const notebook = vscode.workspace.notebookDocuments.find(nb => nb.uri.fsPath === uri.fsPath);
      if (!notebook) {
        return; // Notebook not open in VSCode
      }

      try {
        // Check if kernel state is out of sync
        const syncNeeded = await mcpClient.detectSyncNeeded(uri.fsPath);
        if (syncNeeded) {
          notebooksNeedingSync.add(uri.fsPath);
          updateSyncStatusBar();
        } else {
          // Remove from sync list if no longer needed
          notebooksNeedingSync.delete(uri.fsPath);
          updateSyncStatusBar();
        }
      } catch (error) {
        console.error('Failed to check sync status:', error);
      }
    });

    context.subscriptions.push(notebookWatcher);

    // Register commands
    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.selectEnvironment', async () => {
        await selectEnvironment();
      })
    );

    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.restartServer', async () => {
        await restartServer();
      })
    );

    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.showServerLogs', () => {
        mcpClient.getOutputChannel().show();
      })
    );

    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.syncNotebook', async () => {
        await syncNotebook();
      })
    );

    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.refreshVariables', async () => {
        await variableDashboard.refresh();
      })
    );

    // Show success message
    vscode.window.showInformationMessage('MCP Agent Kernel is ready!');
    console.log('MCP Agent Kernel extension activated successfully');
    
    return {
      mcpClient,
      notebookController,
      variableDashboard
    };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    vscode.window.showErrorMessage(`Failed to activate MCP Agent Kernel: ${errorMessage}`);
    console.error('Activation error:', error);
    throw error;
  }
}

export async function deactivate(): Promise<void> {
  console.log('MCP Agent Kernel extension deactivating...');

  if (syncStatusBar) {
    syncStatusBar.dispose();
  }

  if (mcpClient) {
    await mcpClient.stop();
    mcpClient.dispose();
  }

  console.log('MCP Agent Kernel extension deactivated');
}

/**
 * Update sync status bar visibility and text
 */
function updateSyncStatusBar(): void {
  if (notebooksNeedingSync.size > 0) {
    const count = notebooksNeedingSync.size;
    syncStatusBar.text = `⚠ ${count} notebook${count > 1 ? 's' : ''} out of sync`;
    syncStatusBar.show();
  } else {
    syncStatusBar.hide();
  }
}

/**
 * Command: Sync active notebook from disk
 */
async function syncNotebook(): Promise<void> {
  try {
    const activeNotebook = vscode.window.activeNotebookEditor?.notebook;
    if (!activeNotebook) {
      vscode.window.showWarningMessage('No active notebook to sync.');
      return;
    }

    const notebookPath = activeNotebook.uri.fsPath;
    if (!notebooksNeedingSync.has(notebookPath)) {
      vscode.window.showInformationMessage('This notebook is already in sync.');
      return;
    }

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: `Syncing ${path.basename(notebookPath)}...`,
        cancellable: false,
      },
      async () => {
        await mcpClient.syncStateFromDisk(notebookPath);
      }
    );

    notebooksNeedingSync.delete(notebookPath);
    updateSyncStatusBar();
    vscode.window.showInformationMessage('Notebook synced successfully');
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    vscode.window.showErrorMessage(`Failed to sync notebook: ${errorMessage}`);
  }
}

/**
 * Command: Select Python environment for current notebook
 */
async function selectEnvironment(): Promise<void> {
  try {
    // Get active notebook
    const activeNotebook = vscode.window.activeNotebookEditor?.notebook;
    if (!activeNotebook) {
      vscode.window.showWarningMessage('No active notebook. Please open a notebook first.');
      return;
    }

    // List available environments
    const environments = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Discovering Python environments...',
        cancellable: false,
      },
      async () => {
        return await mcpClient.listEnvironments();
      }
    );

    if (environments.length === 0) {
      vscode.window.showInformationMessage('No Python environments found.');
      return;
    }

    // Show quick pick
    const items = environments.map((env) => ({
      label: env.name,
      description: env.path,
      detail: `${env.type}${env.python_version ? ` (Python ${env.python_version})` : ''}`,
      env,
    }));

    const selected = await vscode.window.showQuickPick(items, {
      placeHolder: 'Select a Python environment for this notebook',
      matchOnDescription: true,
      matchOnDetail: true,
    });

    if (!selected) {
      return;
    }

    // Restart kernel with selected environment
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: `Switching to ${selected.label}...`,
        cancellable: false,
      },
      async () => {
        const notebookPath = activeNotebook.uri.fsPath;
        
        // Stop current kernel
        try {
          await mcpClient.stopKernel(notebookPath);
        } catch {
          // Kernel might not be running
        }

        // Start with new environment
        await mcpClient.startKernel(notebookPath, selected.env.path);
        
        // Update status bar
        notebookController.updateEnvironment({
          name: selected.env.name,
          path: selected.env.path,
          type: selected.env.type,
        });
        
        // Persist environment choice to notebook metadata
        const edit = new vscode.WorkspaceEdit();
        const metadata = { ...activeNotebook.metadata };
        metadata['mcp-jupyter'] = {
          environment: {
            name: selected.env.name,
            path: selected.env.path,
            type: selected.env.type,
          },
        };
        
        // Update notebook metadata
        edit.set(activeNotebook.uri, [
          vscode.NotebookEdit.updateNotebookMetadata(metadata)
        ]);
        await vscode.workspace.applyEdit(edit);
      }
    );

    vscode.window.showInformationMessage(`Switched to ${selected.label}`);
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    vscode.window.showErrorMessage(`Failed to select environment: ${errorMessage}`);
  }
}

/**
 * Command: Restart MCP server
 */
async function restartServer(): Promise<void> {
  try {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Restarting MCP server...',
        cancellable: false,
      },
      async () => {
        await mcpClient.stop();
        await new Promise((resolve) => setTimeout(resolve, 1000));
        await mcpClient.start();
      }
    );

    vscode.window.showInformationMessage('MCP server restarted successfully');
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    vscode.window.showErrorMessage(`Failed to restart server: ${errorMessage}`);
  }
}
