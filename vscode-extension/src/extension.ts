import * as vscode from 'vscode';
import * as path from 'path';
import { McpClient } from './mcpClient';
import { McpNotebookController } from './notebookController';
import { VariableDashboardProvider } from './variableDashboard';
import { checkPythonDependencies, promptInstallDependencies } from './dependencies';
import { SetupManager } from './setupManager';
import { SyncCodeLensProvider } from './syncCodeLensProvider';
import { QuickStartWizard } from './quickStartWizard';
import { HealthCheckDashboard } from './healthCheckDashboard';

let mcpClient: McpClient;
let notebookController: McpNotebookController;
let variableDashboard: VariableDashboardProvider;
let syncStatusBar: vscode.StatusBarItem;
let connectionStatusBar: vscode.StatusBarItem;
let setupManager: SetupManager;
let syncCodeLensProvider: SyncCodeLensProvider;
let quickStartWizard: QuickStartWizard;
let healthCheckDashboard: HealthCheckDashboard;
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

    // Create connection health status bar
    connectionStatusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 101);
    connectionStatusBar.command = 'mcp-jupyter.showServerLogs';
    connectionStatusBar.tooltip = 'MCP Server Connection Status (click to view logs)';
    context.subscriptions.push(connectionStatusBar);
    
    // Subscribe to connection state changes
    mcpClient.onConnectionStateChange((state) => {
      switch (state) {
        case 'connected':
          connectionStatusBar.text = '$(circle-filled) MCP';
          connectionStatusBar.backgroundColor = undefined;
          connectionStatusBar.tooltip = 'MCP Server: Connected';
          break;
        case 'connecting':
          connectionStatusBar.text = '$(sync~spin) MCP';
          connectionStatusBar.backgroundColor = undefined;
          connectionStatusBar.tooltip = 'MCP Server: Connecting...';
          break;
        case 'disconnected':
          connectionStatusBar.text = '$(circle-outline) MCP';
          connectionStatusBar.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
          connectionStatusBar.tooltip = 'MCP Server: Disconnected';
          break;
      }
      connectionStatusBar.show();
    });
    
    // [WEEK 1] Subscribe to connection health changes (heartbeat & reconnection)
    mcpClient.onConnectionHealthChange((health) => {
      if (health.missedHeartbeats > 0) {
        connectionStatusBar.text = `$(warning) MCP (${health.missedHeartbeats} missed)`;
        connectionStatusBar.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
        connectionStatusBar.tooltip = `MCP Server: Connection unstable (${health.missedHeartbeats} missed heartbeats)`;
      } else if (health.reconnectAttempt > 0) {
        connectionStatusBar.text = `$(sync~spin) MCP (retry ${health.reconnectAttempt}/10)`;
        connectionStatusBar.backgroundColor = undefined;
        connectionStatusBar.tooltip = `MCP Server: Reconnecting (attempt ${health.reconnectAttempt}/10)`;
      } else {
        // Healthy connection - restore normal display
        connectionStatusBar.text = '$(circle-filled) MCP';
        connectionStatusBar.backgroundColor = undefined;
        connectionStatusBar.tooltip = 'MCP Server: Connected';
      }
      connectionStatusBar.show();
    });
    
    // Setup manager for managed environment (First-Run flow)
    setupManager = new SetupManager(context);
    
    // [WEEK 2] Quick Start wizard for one-click setup
    quickStartWizard = new QuickStartWizard(context, setupManager, mcpClient);
    quickStartWizard.showIfNeeded();
    context.subscriptions.push(quickStartWizard);
    
    // [WEEK 2] Health check dashboard
    healthCheckDashboard = new HealthCheckDashboard(mcpClient);
    context.subscriptions.push(healthCheckDashboard);

    // Open the walkthrough on first activation (idempotent)
    const isInstalled = context.globalState.get('mcp.hasCompletedSetup', false);
    if (!isInstalled) {
      // Defer opening the walkthrough to ensure VS Code UI is ready
      setTimeout(() => {
        vscode.commands.executeCommand('workbench.action.openWalkthrough', 'warshawsky-research.mcp-agent-kernel#mcp-jupyter-setup');
      }, 500);
    }
    
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
    let skipStart = false;
    if (!depsInstalled) {
      // Non-blocking: notify the user and open the Setup Wizard, but do NOT await any UI input
      vscode.window.showWarningMessage('Python dependencies for the MCP server are missing. Open the Setup Wizard to install them.', 'Open Setup Wizard');
      setTimeout(() => {
        vscode.commands.executeCommand('workbench.action.openWalkthrough', 'warshawsky-research.mcp-agent-kernel#mcp-jupyter-setup');
      }, 500);

      // If the user explicitly configured a pythonPath, attempt to start with it (useful for tests)
      const configuredPath = vscode.workspace.getConfiguration('mcp-jupyter').get<string>('pythonPath');
      mcpClient.getOutputChannel().appendLine(`Debug: configured pythonPath is ${configuredPath}`);
      console.log(`Debug: configured pythonPath is ${configuredPath}`);
      if (configuredPath) {
        try {
          mcpClient.getOutputChannel().appendLine('Debug: attempting to start server with configured pythonPath (direct call)');
          await mcpClient.start();
          mcpClient.getOutputChannel().appendLine('Debug: start succeeded');
          vscode.window.showInformationMessage('MCP server started with configured Python');
        } catch (startErr: any) {
          mcpClient.getOutputChannel().appendLine(`Debug: failed to start server: ${startErr?.message ?? String(startErr)}`);
          vscode.window.showWarningMessage(`Failed to start MCP server with configured Python: ${startErr?.message ?? String(startErr)}. Open the Setup Wizard for troubleshooting.`);
        }
      }

      // If we couldn't attempt a start, skip the normal start block, otherwise allow it to proceed
      skipStart = !configuredPath;
    }

    // Start MCP server unless setup/install was deferred
    if (!skipStart) {
      mcpClient.getOutputChannel().appendLine('Activation: about to call mcpClient.start()');
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: 'Starting MCP Jupyter server...',
          cancellable: false,
        },
        async () => {
          try {
            await mcpClient.start();
          } catch (e) {
            // Show a helpful message rather than throwing and failing activation
            mcpClient.getOutputChannel().appendLine(`Activation: mcpClient.start() failed: ${(e as any)?.message ?? String(e)}`);
            vscode.window.showErrorMessage(`Failed to start MCP server: ${(e as any)?.message ?? String(e)}. Use the Setup Wizard to install or configure the server.`);
          }
        }
      );
    } else {
      mcpClient.getOutputChannel().appendLine('Activation: Skipping server start due to missing or deferred dependency installation');
      console.log('Skipping server start due to missing or deferred dependency installation');
    }

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

    // Create sync CodeLens provider
    syncCodeLensProvider = new SyncCodeLensProvider(mcpClient);
    context.subscriptions.push(
      vscode.languages.registerCodeLensProvider(
        { pattern: '**/*.ipynb' },
        syncCodeLensProvider
      )
    );

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
          syncCodeLensProvider.setSyncNeeded(uri.fsPath, true);
        } else {
          // Remove from sync list if no longer needed
          notebooksNeedingSync.delete(uri.fsPath);
          updateSyncStatusBar();
          syncCodeLensProvider.setSyncNeeded(uri.fsPath, false);
        }
      } catch (error) {
        console.error('Failed to check sync status:', error);
      }
    });

    context.subscriptions.push(notebookWatcher);

    // Register commands
    // [WEEK 2] Quick Start command - one-click setup
    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.quickStart', async () => {
        await quickStartWizard.run();
      })
    );
    
    // [WEEK 2] Health check dashboard command
    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.showHealthCheck', () => {
        healthCheckDashboard.show();
      })
    );
    
    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.openWalkthrough', async () => {
        await vscode.commands.executeCommand('workbench.action.openWalkthrough', 'warshawsky-research.mcp-agent-kernel#mcp-jupyter-setup');
      })
    );

    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.selectRuntime', async () => {
        const pick = await vscode.window.showQuickPick(['Managed Environment', 'System Python'], { placeHolder: 'Select where the MCP server should run' });
        if (!pick) return;

        if (pick === 'Managed Environment') {
          try {
            const venvPath = await setupManager.createManagedEnvironment();
            vscode.window.showInformationMessage(`Managed environment created at ${venvPath}`);
          } catch (e: any) {
            vscode.window.showErrorMessage(`Failed to create managed environment: ${e?.message ?? String(e)}`);
          }
        } else {
          await vscode.workspace.getConfiguration('mcp-jupyter').update('pythonPath', '', vscode.ConfigurationTarget.Global);
          vscode.window.showInformationMessage('Using system Python for MCP server');
        }
      })
    );

    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.installServer', async () => {
        try {
          const venvPath = await setupManager.createManagedEnvironment();
          await setupManager.installDependencies(venvPath);
          vscode.window.showInformationMessage('MCP server installed in managed environment');

          // Try to start the server immediately so the user gets feedback
          try {
            await vscode.window.withProgress({ title: 'Starting MCP server...', location: vscode.ProgressLocation.Notification }, async () => {
              await mcpClient.start();
            });
            vscode.window.showInformationMessage('MCP server started successfully');
          } catch (startErr: any) {
            vscode.window.showWarningMessage(`Installed but failed to start server: ${startErr?.message ?? String(startErr)}. Open the Setup Wizard for troubleshooting.`);
          }
        } catch (e: any) {
          vscode.window.showErrorMessage(`Install failed: ${e?.message ?? String(e)}`);
        }
      })
    );

    context.subscriptions.push(
      vscode.commands.registerCommand('mcp-jupyter.testConnection', async () => {
        try {
          await vscode.window.withProgress({ title: 'Testing MCP server connection...', location: vscode.ProgressLocation.Notification }, async () => {
            // Restart server to ensure config changes take effect
            if (mcpClient.getStatus() !== 'stopped') {
              try { await mcpClient.stop(); } catch {}
            }
            await mcpClient.start();
          });
          vscode.window.showInformationMessage('MCP server connection successful');
        } catch (e: any) {
          vscode.window.showErrorMessage(`Connection test failed: ${e?.message ?? String(e)}`);
        }
      })
    );

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

  if (connectionStatusBar) {
    connectionStatusBar.dispose();
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
    syncCodeLensProvider.setSyncNeeded(notebookPath, false);
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
