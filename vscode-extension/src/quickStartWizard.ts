import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { SetupManager } from './setupManager';
import { McpClient } from './mcpClient';

/**
 * Guides users through the initial setup for MCP Jupyter.
 * It supports a silent, automatic installation for a frictionless experience,
 * as well as a manual, interactive flow for more control.
 */
export class QuickStartWizard {
  private statusBarItem: vscode.StatusBarItem;
  private isAutoInstalling = false;

  constructor(
    private context: vscode.ExtensionContext,
    private setupManager: SetupManager,
    private mcpClient: McpClient
  ) {
    // Status bar item for easy access to the setup
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100
    );
    this.statusBarItem.command = 'mcp-jupyter.quickStart';
    this.statusBarItem.text = '$(rocket) MCP Jupyter Setup';
    this.statusBarItem.tooltip = 'Set up MCP Jupyter';
  }

  /**
   * Determines if the setup process should be shown and initiates a silent install if needed.
   */
  public showIfNeeded(): void {
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    const showWizard = config.get<boolean>('showSetupWizard', true);

    if (!showWizard) {
      return;
    }

    const isSetupComplete = this.context.globalState.get('mcp.hasCompletedSetup', false);
    if (!isSetupComplete) {
      // For a better UX, attempt a silent, automatic installation in the background.
      this.runSilentAutoInstall();
    } else {
      this.statusBarItem.hide();
    }
  }

  /**
   * Performs a silent, background installation to provide a zero-friction onboarding experience.
   * This avoids disruptive wizards and gets the user started quickly.
   */
  private async runSilentAutoInstall(): Promise<void> {
    if (this.isAutoInstalling) return;

    const alreadyAttempted = this.context.workspaceState.get('mcp.autoInstallAttempted', false);
    if (alreadyAttempted) {
      // If auto-install failed before, show the manual setup option in the status bar.
      this.statusBarItem.show();
      return;
    }

    this.isAutoInstalling = true;
    await this.context.workspaceState.update('mcp.autoInstallAttempted', true);

    const statusMessage = vscode.window.setStatusBarMessage(
      '$(sync~spin) Installing MCP Jupyter dependencies in the background...'
    );

    try {
      const venvPath = await this.setupManager.createManagedEnvironmentSilent();
      await this.setupManager.installDependenciesSilent(venvPath);
      await this.mcpClient.start();

      await this.context.globalState.update('mcp.hasCompletedSetup', true);
      this.statusBarItem.hide();
      statusMessage.dispose();

      vscode.window.showInformationMessage(
        '✅ MCP Jupyter Ready! Select the "MCP Kernel" in any notebook to start.',
        'Open Example Notebook'
      ).then(choice => {
        if (choice === 'Open Example Notebook') {
          this.openTestNotebook();
        }
      });

      // Briefly flash the kernel picker to guide the user.
      vscode.commands.executeCommand('notebook.selectKernel');

    } catch (error) {
      statusMessage.dispose();
      this.isAutoInstalling = false;

      const errorMessage = error instanceof Error ? error.message : String(error);
      vscode.window.showErrorMessage(
        `MCP Jupyter setup failed: ${errorMessage}`,
        'Open Setup Wizard',
        'Show Logs'
      ).then(choice => {
        if (choice === 'Open Setup Wizard') {
          this.run(); // Fall back to the manual, interactive wizard.
        } else if (choice === 'Show Logs') {
          this.mcpClient.getOutputChannel().show();
        }
      });

      this.statusBarItem.show();
    }
  }

  /**
   * Hides the setup status bar item.
   */
  public hide(): void {
    this.statusBarItem.hide();
  }

  /**
   * Main entry point for the Quick Start command.
   */
  public async run(): Promise<void> {
    const isSetupComplete = this.context.globalState.get('mcp.hasCompletedSetup', false);

    if (isSetupComplete) {
      const choice = await vscode.window.showInformationMessage(
        'MCP Jupyter is already set up.',
        'Test Connection',
        'Reinstall'
      );

      if (choice === 'Test Connection') {
        return this.testConnection();
      } else if (choice === 'Reinstall') {
        return this.runSetupFlow();
      }
      return;
    }
    return this.runSetupFlow();
  }

  /**
   * Runs the full, interactive setup flow with progress notifications.
   */
  private async runSetupFlow(): Promise<void> {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Setting up MCP Jupyter...',
        cancellable: false,
      },
      async (progress) => {
        try {
          progress.report({ increment: 10, message: 'Checking for existing server...' });
          const serverStatus = this.mcpClient.getStatus();
          if (serverStatus === 'running') {
            await this.context.globalState.update('mcp.hasCompletedSetup', true);
            this.hide();
            vscode.window.showInformationMessage('✅ MCP Jupyter server is already running!');
            return;
          }

          progress.report({ increment: 10, message: 'Selecting installation mode...' });
          const mode = await this.selectMode();
          if (!mode) throw new Error('Setup cancelled by user.');

          if (mode === 'managed') {
            progress.report({ increment: 20, message: 'Creating isolated environment...' });
            const venvPath = await this.setupManager.createManagedEnvironment();
            progress.report({ increment: 30, message: 'Installing dependencies...' });
            await this.setupManager.installDependencies(venvPath);
          } else if (mode === 'existing') {
            progress.report({ increment: 20, message: 'Configuring Python path...' });
            const pythonPath = await this.selectPythonExecutable();
            if (!pythonPath) throw new Error('No Python executable selected.');
            await vscode.workspace.getConfiguration('mcp-jupyter').update('pythonPath', pythonPath, vscode.ConfigurationTarget.Global);
          } else {
            progress.report({ increment: 30, message: 'Configuring remote connection...' });
            const configured = await this.configureRemoteConnection();
            if (!configured) throw new Error('Remote configuration cancelled.');
          }

          progress.report({ increment: 20, message: 'Starting server...' });
          await this.mcpClient.start();

          progress.report({ increment: 10, message: 'Verifying connection...' });
          const finalStatus = this.mcpClient.getStatus();
          if (finalStatus !== 'running') throw new Error('Server started but is not responding.');

          await this.context.globalState.update('mcp.hasCompletedSetup', true);
          this.hide();

          const choice = await vscode.window.showInformationMessage(
            '🎉 MCP Jupyter is ready! Select the "MCP Kernel" to get started.',
            'Open Example Notebook',
            'Done'
          );

          if (choice === 'Open Example Notebook') {
            await this.openTestNotebook();
          }

        } catch (error) {
          vscode.window.showErrorMessage(
            `Setup failed: ${error instanceof Error ? error.message : String(error)}`,
            'Show Logs',
            'Try Again'
          ).then(choice => {
            if (choice === 'Show Logs') {
              this.mcpClient.getOutputChannel().show();
            } else if (choice === 'Try Again') {
              this.run();
            }
          });
        }
      }
    );
  }

  /**
   * Prompts the user to select an installation mode.
   */
  private async selectMode(): Promise<'managed' | 'existing' | 'remote' | undefined> {
    const items: Array<vscode.QuickPickItem & { mode: 'managed' | 'existing' | 'remote' }> = [
      {
        label: '$(rocket) Automatic Setup',
        description: '⭐ Recommended',
        detail: 'Creates an isolated environment for MCP Jupyter automatically.',
        mode: 'managed',
        picked: true,
      },
      {
        label: '$(folder-library) Use an Existing Python Environment',
        description: 'Advanced',
        detail: 'Use a Python/Conda environment you already have. You must install dependencies manually.',
        mode: 'existing'
      },
      {
        label: '$(remote) Connect to a Remote MCP Jupyter Server',
        description: 'For Teams/Enterprise',
        detail: 'Connect to an MCP Jupyter server running on another machine.',
        mode: 'remote'
      }
    ];

    const selected = await vscode.window.showQuickPick(items, {
      placeHolder: 'Choose a setup method for MCP Jupyter',
      ignoreFocusOut: true,
    });

    return selected?.mode;
  }

  private async selectPythonExecutable(): Promise<string | undefined> {
    const uris = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      title: 'Select Python Executable',
      filters: {
        'Python': ['exe', 'py', '']
      }
    });
    return uris?.[0]?.fsPath;
  }

  private async configureRemoteConnection(): Promise<boolean> {
    const host = await vscode.window.showInputBox({
      prompt: 'Enter the hostname or IP address of the remote server',
      value: '127.0.0.1',
      ignoreFocusOut: true
    });
    if (!host) return false;

    const port = await vscode.window.showInputBox({
      prompt: 'Enter the port number of the remote server',
      value: '3000',
      validateInput: val => (parseInt(val) > 0 && parseInt(val) < 65536) ? null : 'Invalid port number.',
      ignoreFocusOut: true
    });
    if (!port) return false;
    
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    await config.update('serverMode', 'connect', vscode.ConfigurationTarget.Global);
    await config.update('remoteHost', host, vscode.ConfigurationTarget.Global);
    await config.update('remotePort', parseInt(port), vscode.ConfigurationTarget.Global);

    return true;
  }

  private async testConnection(): Promise<void> {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Testing MCP Jupyter Server Connection...',
        cancellable: false,
      },
      async (progress) => {
        try {
          const status = this.mcpClient.getStatus();
          const connectionState = this.mcpClient.getConnectionState();

          progress.report({ message: 'Checking server status...' });
          if (status === 'running' && connectionState === 'connected') {
            progress.report({ message: 'Executing test query...' });
            // A simple query to verify the connection is live.
            await this.mcpClient.listEnvironments();
            vscode.window.showInformationMessage('✅ Connection to MCP Jupyter server is successful!');
          } else {
            throw new Error(`Server status: ${status}, Connection: ${connectionState}`);
          }
        } catch (error) {
          vscode.window.showErrorMessage(
            `Connection test failed: ${error instanceof Error ? error.message : String(error)}`,
            'Show Logs',
            'Restart Server'
          ).then(choice => {
            if (choice === 'Show Logs') {
              this.mcpClient.getOutputChannel().show();
            } else if (choice === 'Restart Server') {
              vscode.commands.executeCommand('mcp-jupyter.restartServer');
            }
          });
        }
      }
    );
  }

  /**
   * Creates and opens an example notebook to guide the user.
   * If the notebook already exists, it prompts before overwriting.
   */
  private async openTestNotebook(): Promise<void> {
    const examplePath = path.join(this.context.extensionPath, 'examples', 'quickstart.ipynb');
    const examplesDir = path.dirname(examplePath);

    if (fs.existsSync(examplePath)) {
      const choice = await vscode.window.showInformationMessage(
        'An example notebook already exists.',
        'Open Existing',
        'Overwrite'
      );

      if (choice === 'Open Existing' || !choice) {
        const doc = await vscode.workspace.openNotebookDocument(vscode.Uri.file(examplePath));
        await vscode.window.showNotebookDocument(doc);
        return;
      }
    }
    
    if (!fs.existsSync(examplesDir)) {
      fs.mkdirSync(examplesDir, { recursive: true });
    }

    const exampleNotebook = {
      cells: [
        {
          cell_type: 'markdown',
          source: [
            '# Welcome to MCP Jupyter!\n',
            'This notebook is a quick tour of the key features.\n',
            '## Step 1: Select the MCP Kernel\n',
            'If you haven\'t already, click the kernel picker in the top-right and select **MCP Kernel**.'
          ]
        },
        {
          cell_type: 'code',
          source: [
            '# Test basic execution\n',
            'import sys\n',
            'print("Hello from MCP Jupyter!")\n',
            'print(f"Using Python {sys.version}")'
          ]
        },
        {
          cell_type: 'markdown',
          source: ['## Step 2: Explore Your Data\n', 'Create a DataFrame and see how MCP Jupyter helps you explore it.']
        },
        {
          cell_type: 'code',
          source: [
            'import pandas as pd\n',
            'data = pd.DataFrame({\n',
            '    "city": ["New York", "London", "Tokyo", "Paris", "Sydney"],\n',
            '    "temperature": [15, 12, 20, 18, 25],\n',
            '    "humidity": [65, 75, 60, 80, 70]\n',
            '})\n',
            'print("DataFrame created. Check the MCP Variables panel in the sidebar!")'
          ]
        },
        {
          cell_type: 'markdown',
          source: ['## Next Steps\n', 'You are now ready to use MCP Jupyter. Try some of the superpowers, like running SQL queries on your DataFrames or generating automated EDA reports.']
        }
      ],
      metadata: {
        kernelspec: {
          display_name: 'Python 3',
          language: 'python',
          name: 'python3'
        }
      },
      nbformat: 4,
      nbformat_minor: 2
    };

    fs.writeFileSync(examplePath, JSON.stringify(exampleNotebook, null, 2));

    const doc = await vscode.workspace.openNotebookDocument(vscode.Uri.file(examplePath));
    await vscode.window.showNotebookDocument(doc);
  }

  /**
   * Disposes of the status bar item when the extension is deactivated.
   */
  public dispose(): void {
    this.statusBarItem.dispose();
  }
}
