import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { SetupManager } from './setupManager';
import { McpClient } from './mcpClient';

/**
 * Week 2: Quick Start Wizard
 * One-click setup that guides users through installation
 * 
 * [DS UX FIX] Now supports "Invisible Setup" mode for zero-friction onboarding.
 * Data scientists don't want wizards - they want their notebook to just work.
 */
export class QuickStartWizard {
  private statusBarItem: vscode.StatusBarItem;
  private isAutoInstalling = false;

  constructor(
    private context: vscode.ExtensionContext,
    private setupManager: SetupManager,
    private mcpClient: McpClient
  ) {
    // Create status bar item for quick access
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100
    );
    this.statusBarItem.command = 'mcp-jupyter.quickStart';
    this.statusBarItem.text = '$(rocket) Quick Start MCP';
    this.statusBarItem.tooltip = 'Set up MCP Jupyter in one click';
  }

  /**
   * Show status bar if setup is not complete
   * [DS UX FIX] Now triggers silent auto-install instead of showing notifications
   */
  public showIfNeeded(): void {
    const isSetupComplete = this.context.globalState.get('mcp.hasCompletedSetup', false);
    if (!isSetupComplete) {
      // [DS UX FIX] Start silent auto-install - no wizard, no prompts
      this.runSilentAutoInstall();
    } else {
      this.statusBarItem.hide();
    }
  }

  /**
   * [DS UX FIX] Silent auto-install for zero-friction onboarding
   * Data scientists don't want to click through setup wizards.
   * This runs in the background with minimal notifications.
   */
  private async runSilentAutoInstall(): Promise<void> {
    // Prevent duplicate auto-installs
    if (this.isAutoInstalling) return;
    
    const alreadyAttempted = this.context.workspaceState.get('mcp.autoInstallAttempted', false);
    if (alreadyAttempted) {
      // Show status bar for manual retry if auto-install already attempted this session
      this.statusBarItem.show();
      return;
    }
    
    this.isAutoInstalling = true;
    await this.context.workspaceState.update('mcp.autoInstallAttempted', true);

    // Show discrete toast notification (not a modal wizard)
    const statusMessage = vscode.window.setStatusBarMessage(
      '$(sync~spin) Installing AI Kernel dependencies in background...'
    );

    try {
      // Step 1: Create managed environment (silent)
      const venvPath = await this.setupManager.createManagedEnvironmentSilent();
      
      // Step 2: Install dependencies (silent)
      await this.setupManager.installDependenciesSilent(venvPath);
      
      // Step 3: Start server
      await this.mcpClient.start();
      
      // Success! Mark setup complete
      await this.context.globalState.update('mcp.hasCompletedSetup', true);
      this.statusBarItem.hide();
      statusMessage.dispose();
      
      // Show success toast with kernel hint
      vscode.window.showInformationMessage(
        '✅ AI Agent Ready! Select "MCP Agent Kernel" in any notebook to start.',
        'Open Example Notebook'
      ).then(choice => {
        if (choice === 'Open Example Notebook') {
          this.openTestNotebook();
        }
      });
      
      // Flash the kernel picker to draw attention
      vscode.commands.executeCommand('notebook.selectKernel');
      
    } catch (error) {
      statusMessage.dispose();
      this.isAutoInstalling = false;
      
      // Only show error on failure - don't bother user if it worked
      const errorMessage = error instanceof Error ? error.message : String(error);
      
      // Show discrete error with option to manually configure
      vscode.window.showErrorMessage(
        `AI Kernel setup failed: ${errorMessage}`,
        'Open Setup Wizard',
        'Show Logs'
      ).then(choice => {
        if (choice === 'Open Setup Wizard') {
          this.run(); // Fall back to manual wizard
        } else if (choice === 'Show Logs') {
          this.mcpClient.getOutputChannel().show();
        }
      });
      
      // Show status bar for manual retry
      this.statusBarItem.show();
    }
  }

  /**
   * [LEGACY] Show prominent welcome notification for first-time users
   * Now deprecated in favor of silent auto-install, but kept for manual invocation
   */
  private async showWelcomeNotification(): Promise<void> {
    // Don't show if we already showed it this session
    const shownThisSession = this.context.workspaceState.get('mcp.welcomeShownThisSession', false);
    if (shownThisSession) return;
    
    await this.context.workspaceState.update('mcp.welcomeShownThisSession', true);
    
    const choice = await vscode.window.showInformationMessage(
      '🚀 Welcome to MCP Jupyter! Set up your AI Data Science Assistant in 60 seconds.',
      'Setup Now (Recommended)',
      'Later'
    );
    
    if (choice === 'Setup Now (Recommended)') {
      await this.run();
    }
  }

  /**
   * Hide status bar after successful setup
   */
  public hide(): void {
    this.statusBarItem.hide();
  }

  /**
   * Main entry point: Quick Start command
   */
  public async run(): Promise<void> {
    // Check if already set up
    const isSetupComplete = this.context.globalState.get('mcp.hasCompletedSetup', false);
    
    if (isSetupComplete) {
      const choice = await vscode.window.showInformationMessage(
        'MCP Jupyter is already set up. What would you like to do?',
        'Test Connection',
        'Reinstall',
        'Cancel'
      );

      if (choice === 'Test Connection') {
        return this.testConnection();
      } else if (choice === 'Reinstall') {
        return this.runSetupFlow();
      }
      return;
    }

    // Run setup flow
    return this.runSetupFlow();
  }

  /**
   * Run the complete setup flow
   */
  private async runSetupFlow(): Promise<void> {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Setting up MCP Jupyter...',
        cancellable: false,
      },
      async (progress, token) => {
        try {
          // Step 1: Check for existing server
          progress.report({ increment: 10, message: 'Checking for existing server...' });
          await this.sleep(500);

          const serverStatus = this.mcpClient.getStatus();
          if (serverStatus === 'running') {
            const choice = await vscode.window.showInformationMessage(
              '✅ MCP server is already running!',
              'Test It',
              'View Logs'
            );
            
            if (choice === 'Test It') {
              await this.openTestNotebook();
            } else if (choice === 'View Logs') {
              this.mcpClient.getOutputChannel().show();
            }
            
            await this.context.globalState.update('mcp.hasCompletedSetup', true);
            this.hide();
            return;
          }

          // Step 2: Choose installation mode
          progress.report({ increment: 10, message: 'Selecting installation mode...' });
          const mode = await this.selectMode();
          if (!mode) {
            throw new Error('Setup cancelled by user');
          }

          if (mode === 'managed') {
            // Step 3a: Create managed environment
            progress.report({ increment: 20, message: 'Creating isolated environment...' });
            const venvPath = await this.setupManager.createManagedEnvironment();
            
            // Step 3b: Install dependencies
            progress.report({ increment: 30, message: 'Installing dependencies...' });
            await this.setupManager.installDependencies(venvPath);
            
            progress.report({ increment: 20, message: 'Starting server...' });
          } else if (mode === 'existing') {
            // Step 3: Select existing Python
            progress.report({ increment: 20, message: 'Configuring Python path...' });
            const pythonPath = await this.selectPythonExecutable();
            if (!pythonPath) {
              throw new Error('No Python executable selected');
            }
            
            // Save configuration
            await vscode.workspace.getConfiguration('mcp-jupyter').update(
              'pythonPath',
              pythonPath,
              vscode.ConfigurationTarget.Global
            );
            
            progress.report({ increment: 50, message: 'Starting server...' });
          } else {
            // Remote mode
            progress.report({ increment: 30, message: 'Configuring remote connection...' });
            const configured = await this.configureRemoteConnection();
            if (!configured) {
              throw new Error('Remote configuration cancelled');
            }
            
            progress.report({ increment: 40, message: 'Connecting to remote server...' });
          }

          // Step 4: Start the server
          try {
            await this.mcpClient.start();
          } catch (error) {
            throw new Error(`Failed to start server: ${error instanceof Error ? error.message : String(error)}`);
          }

          // Step 5: Verify connection
          progress.report({ increment: 10, message: 'Verifying connection...' });
          await this.sleep(1000);

          const finalStatus = this.mcpClient.getStatus();
          if (finalStatus !== 'running') {
            throw new Error('Server started but not responding');
          }

          // Success!
          await this.context.globalState.update('mcp.hasCompletedSetup', true);
          this.hide();
          
          const choice = await vscode.window.showInformationMessage(
            '🎉 MCP Jupyter is ready! Try executing a cell with the 🤖 MCP Agent Kernel.',
            'Open Example Notebook',
            'View Documentation',
            'Done'
          );

          if (choice === 'Open Example Notebook') {
            await this.openTestNotebook();
          } else if (choice === 'View Documentation') {
            vscode.env.openExternal(vscode.Uri.parse('https://github.com/example/mcp-jupyter'));
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
   * Select installation mode
   * [FRICTION FIX #2] Renamed options for clarity, "Automatic" is default
   */
  private async selectMode(): Promise<'managed' | 'existing' | 'remote' | undefined> {
    const items: Array<vscode.QuickPickItem & { mode: 'managed' | 'existing' | 'remote' }> = [
      {
        label: '$(rocket) Automatic Setup',
        description: '⭐ Recommended - One-click installation',
        detail: 'Installs everything automatically in 60 seconds. No configuration needed.',
        mode: 'managed',
        picked: true  // Pre-select this option
      },
      {
        label: '$(folder-library) Use My Python Environment',
        description: 'Advanced - For users with existing setups',
        detail: 'Use your own Python/Conda environment. You handle the dependencies.',
        mode: 'existing'
      },
      {
        label: '$(remote) Connect to Remote Server',
        description: 'Advanced - Team/Enterprise deployment',
        detail: 'Connect to an MCP server running on another machine or container.',
        mode: 'remote'
      }
    ];

    const selected = await vscode.window.showQuickPick(items, {
      placeHolder: '🚀 Choose setup method (Automatic recommended)',
      ignoreFocusOut: true,
      matchOnDescription: true,
      matchOnDetail: true
    });

    return selected?.mode;
  }

  /**
   * Select Python executable from available options
   */
  private async selectPythonExecutable(): Promise<string | undefined> {
    // Try to use Python extension's API if available
    try {
      const pythonExt = vscode.extensions.getExtension('ms-python.python');
      if (pythonExt) {
        await pythonExt.activate();
        const pythonApi = pythonExt.exports;
        
        // Get active interpreter
        const activeInterpreter = pythonApi.settings.getExecutionDetails?.();
        if (activeInterpreter) {
          const choice = await vscode.window.showInformationMessage(
            `Use active Python interpreter?\n${activeInterpreter.execCommand}`,
            'Yes',
            'Choose Different'
          );
          
          if (choice === 'Yes') {
            return Array.isArray(activeInterpreter.execCommand) 
              ? activeInterpreter.execCommand[0] 
              : activeInterpreter.execCommand;
          }
        }
      }
    } catch (error) {
      // Python extension not available or API changed
    }

    // Fallback: Manual file picker
    const uris = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      title: 'Select Python Executable',
      filters: {
        'Python': ['exe', 'py', ''] // Allow extensionless files on Unix
      }
    });

    return uris?.[0]?.fsPath;
  }

  /**
   * Configure remote connection parameters
   */
  private async configureRemoteConnection(): Promise<boolean> {
    const host = await vscode.window.showInputBox({
      prompt: 'Enter remote server host',
      placeHolder: 'example.com or 192.168.1.100',
      value: '127.0.0.1',
      ignoreFocusOut: true
    });

    if (!host) return false;

    const port = await vscode.window.showInputBox({
      prompt: 'Enter remote server port',
      placeHolder: '3000',
      value: '3000',
      validateInput: (value) => {
        const num = parseInt(value);
        if (isNaN(num) || num < 1 || num > 65535) {
          return 'Port must be between 1 and 65535';
        }
        return undefined;
      },
      ignoreFocusOut: true
    });

    if (!port) return false;

    const token = await vscode.window.showInputBox({
      prompt: 'Enter session token (optional)',
      placeHolder: 'Leave empty if server has no authentication',
      password: true,
      ignoreFocusOut: true
    });

    // Save configuration
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    await config.update('serverMode', 'connect', vscode.ConfigurationTarget.Global);
    await config.update('remoteHost', host, vscode.ConfigurationTarget.Global);
    await config.update('remotePort', parseInt(port), vscode.ConfigurationTarget.Global);
    
    if (token) {
      await config.update('sessionToken', token, vscode.ConfigurationTarget.Global);
    }

    return true;
  }

  /**
   * Test server connection
   */
  private async testConnection(): Promise<void> {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Testing MCP Server Connection...',
        cancellable: false,
      },
      async (progress) => {
        try {
          const status = this.mcpClient.getStatus();
          const connectionState = this.mcpClient.getConnectionState();
          
          progress.report({ message: 'Checking server status...' });
          await this.sleep(500);

          if (status === 'running' && connectionState === 'connected') {
            // Try a simple operation
            progress.report({ message: 'Executing test query...' });
            try {
              const envs = await this.mcpClient.listEnvironments();
              
              vscode.window.showInformationMessage(
                `✅ Connection successful!\n\nFound ${envs.length} Python environment(s)`,
                'View Logs'
              ).then(choice => {
                if (choice === 'View Logs') {
                  this.mcpClient.getOutputChannel().show();
                }
              });
            } catch (error) {
              throw new Error(`Server responded but query failed: ${error}`);
            }
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
   * Open example/test notebook
   */
  private async openTestNotebook(): Promise<void> {
    const examplePath = path.join(this.context.extensionPath, 'examples', 'quickstart.ipynb');
    
    // Check if example notebook already exists
    if (fs.existsSync(examplePath)) {
      // Check if it's been modified (compare file size as a simple heuristic)
      const stats = fs.statSync(examplePath);
      const expectedSize = 2500; // Approximate size of generated notebook
      
      // If file size is significantly different, user likely modified it
      if (Math.abs(stats.size - expectedSize) > 500) {
        const choice = await vscode.window.showInformationMessage(
          'Example notebook already exists and may have been modified. Overwrite?',
          'Open Existing',
          'Overwrite',
          'Cancel'
        );
        
        if (choice === 'Cancel') {
          return;
        } else if (choice === 'Open Existing') {
          const doc = await vscode.workspace.openNotebookDocument(vscode.Uri.file(examplePath));
          await vscode.window.showNotebookDocument(doc);
          return;
        }
        // If 'Overwrite', continue to recreate
      }
    }
    
    // Create example notebook if it doesn't exist or user chose to overwrite
    const examplesDir = path.dirname(examplePath);
    if (!fs.existsSync(examplesDir)) {
      fs.mkdirSync(examplesDir, { recursive: true });
    }

    const exampleNotebook = {
      cells: [
          {
            cell_type: 'markdown',
            metadata: {},
            source: [
              '# MCP Jupyter Quick Start\n',
              '\n',
              'Welcome to MCP Jupyter! This notebook will help you get started.\n',
              '\n',
              '## Step 1: Select the MCP Agent Kernel\n',
              '\n',
              'Click the kernel picker in the top-right and select **🤖 MCP Agent Kernel**'
            ]
          },
          {
            cell_type: 'code',
            execution_count: null,
            metadata: {},
            outputs: [],
            source: [
              '# Test basic execution\n',
              'print("Hello from MCP Jupyter!")\n',
              'print(f"Python version: {__import__(\'sys\').version}")'
            ]
          },
          {
            cell_type: 'code',
            execution_count: null,
            metadata: {},
            outputs: [],
            source: [
              '# Test variable inspection\n',
              'import pandas as pd\n',
              'import numpy as np\n',
              '\n',
              'data = pd.DataFrame({\n',
              '    "name": ["Alice", "Bob", "Charlie"],\n',
              '    "age": [25, 30, 35],\n',
              '    "score": [85.5, 92.0, 88.5]\n',
              '})\n',
              '\n',
              'data.head()'
            ]
          },
          {
            cell_type: 'markdown',
            metadata: {},
            source: [
              '## Step 2: View Variables\n',
              '\n',
              'Open the **MCP Variables** panel in the sidebar to see all defined variables with their types and memory usage.'
            ]
          },
          {
            cell_type: 'code',
            execution_count: null,
            metadata: {},
            outputs: [],
            source: [
              '# Test streaming output\n',
              'import time\n',
              '\n',
              'for i in range(5):\n',
              '    print(f"Processing step {i+1}/5...")\n',
              '    time.sleep(0.5)\n',
              '\n',
              'print("✅ Done!")'
            ]
          },
          {
            cell_type: 'markdown',
            metadata: {},
            source: [
              '## Next Steps\n',
              '\n',
              '- Try executing cells with AI agents (they share the same kernel state!)\n',
              '- Check out the Variable Dashboard for real-time variable inspection\n',
              '- Explore automatic environment switching with different Python environments\n',
              '\n',
              '📚 [View Documentation](https://github.com/example/mcp-jupyter)'
            ]
          }
        ],
        metadata: {
          kernelspec: {
            display_name: 'Python 3',
            language: 'python',
            name: 'python3'
          },
          language_info: {
            name: 'python',
            version: '3.10.0'
          }
        },
        nbformat: 4,
        nbformat_minor: 4
    };

    fs.writeFileSync(examplePath, JSON.stringify(exampleNotebook, null, 2));

    // Open the notebook
    const doc = await vscode.workspace.openNotebookDocument(vscode.Uri.file(examplePath));
    await vscode.window.showNotebookDocument(doc);
  }

  /**
   * Utility: Sleep for specified milliseconds
   */
  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Dispose resources
   */
  public dispose(): void {
    this.statusBarItem.dispose();
  }
}
