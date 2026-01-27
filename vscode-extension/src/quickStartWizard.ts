import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { SetupManager } from './setupManager';
import { McpClient } from './mcpClient';
import { SetupWebview } from './SetupWebview';

export class QuickStartWizard {
  private statusBarItem: vscode.StatusBarItem;
  private isAutoInstalling = false;
  private setupWebview: SetupWebview;

  constructor(
    private context: vscode.ExtensionContext,
    private setupManager: SetupManager,
    private mcpClient: McpClient
  ) {
    this.setupWebview = new SetupWebview(context, this.runSetup.bind(this));
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100
    );
    this.statusBarItem.command = 'mcp-jupyter.quickStart';
    this.statusBarItem.text = '$(rocket) MCP Jupyter Setup';
    this.statusBarItem.tooltip = 'Set up MCP Jupyter';
  }

  public showIfNeeded(): void {
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    const showWizard = config.get<boolean>('showSetupWizard', true);
    if (!showWizard) return;

    const isSetupComplete = this.context.globalState.get('mcp.hasCompletedSetup', false);
    if (!isSetupComplete) {
      this.runSilentAutoInstall();
    } else {
      this.statusBarItem.hide();
    }
  }

  private async runSilentAutoInstall(): Promise<void> {
    if (this.isAutoInstalling) return;
    const alreadyAttempted = this.context.workspaceState.get('mcp.autoInstallAttempted', false);
    if (alreadyAttempted) {
      this.statusBarItem.show();
      return;
    }

    this.isAutoInstalling = true;
    await this.context.workspaceState.update('mcp.autoInstallAttempted', true);
    const statusMessage = vscode.window.setStatusBarMessage('$(sync~spin) Installing MCP Jupyter...');

    try {
      const venvPath = await this.setupManager.createManagedEnvironmentSilent();
      await this.setupManager.installDependenciesSilent(venvPath);
      await this.mcpClient.start();
      await this.context.globalState.update('mcp.hasCompletedSetup', true);
      this.statusBarItem.hide();
      statusMessage.dispose();
      vscode.window.showInformationMessage('✅ MCP Jupyter Ready! Select "MCP Kernel" to start.', 'Open Example Notebook').then(choice => {
          if (choice === 'Open Example Notebook') this.openTestNotebook();
      });
    } catch (error) {
      statusMessage.dispose();
      this.isAutoInstalling = false;
      vscode.window.showErrorMessage(`MCP Jupyter auto-setup failed.`, 'Open Setup').then(choice => {
        if (choice === 'Open Setup') this.setupWebview.show();
      });
      this.statusBarItem.show();
    }
  }

  public async runSetup(mode: 'managed' | 'existing' | 'remote', data?: any): Promise<void> {
    this.setupWebview.updateStatus(`Starting setup for mode: ${mode}...\n`);
    try {
      if (mode === 'managed') {
        this.setupWebview.updateStatus('Creating isolated environment...\n');
        const venvPath = await this.setupManager.createManagedEnvironment();
        this.setupWebview.updateStatus('Installing dependencies...\n');
        await this.setupManager.installDependencies(venvPath);
      } else if (mode === 'existing') {
        if (!data.pythonPath) {
          this.setupWebview.updateStatus('Python path is required for existing environment setup.\n');
          return;
        }
        this.setupWebview.updateStatus(`Using Python from: ${data.pythonPath}\n`);
        await vscode.workspace.getConfiguration('mcp-jupyter').update('pythonPath', data.pythonPath, vscode.ConfigurationTarget.Global);
        this.setupWebview.updateStatus('You may need to install dependencies manually.\n');
      } else if (mode === 'remote') {
        if (!data.host || !data.port) {
          this.setupWebview.updateStatus('Host and port are required for remote setup.\n');
          return;
        }
        this.setupWebview.updateStatus(`Connecting to remote server at ${data.host}:${data.port}...\n`);
        const config = vscode.workspace.getConfiguration('mcp-jupyter');
        await config.update('serverMode', 'connect', vscode.ConfigurationTarget.Global);
        await config.update('remoteHost', data.host, vscode.ConfigurationTarget.Global);
        await config.update('remotePort', parseInt(data.port), vscode.ConfigurationTarget.Global);
      }

      this.setupWebview.updateStatus('Starting MCP Jupyter server...\n');
      await this.mcpClient.start();

      await this.context.globalState.update('mcp.hasCompletedSetup', true);
      this.setupWebview.updateStatus('\n🎉 MCP Jupyter is ready! You can now close this tab.\n');
      this.hide();
      this.openTestNotebook();

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.setupWebview.updateStatus(`\n❌ Setup failed: ${errorMessage}`);
    }
  }

  public hide(): void {
    this.statusBarItem.hide();
  }

  public run(): void {
    this.setupWebview.show();
  }

  private async openTestNotebook(): Promise<void> {
    const examplePath = path.join(this.context.extensionPath, 'examples', 'quickstart.ipynb');
    const examplesDir = path.dirname(examplePath);

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

  public dispose(): void {
    this.statusBarItem.dispose();
  }
}
