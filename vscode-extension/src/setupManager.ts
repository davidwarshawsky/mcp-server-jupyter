import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { spawn } from 'child_process';

export class SetupManager {
  constructor(private context: vscode.ExtensionContext) {}

  public getManagedVenvPath(): string {
    return path.join(this.context.globalStorageUri.fsPath, 'mcp-venv');
  }

  private pythonExeForVenv(venvPath: string): string {
    return path.join(venvPath, process.platform === 'win32' ? 'Scripts\python.exe' : 'bin/python');
  }

  async createManagedEnvironment(): Promise<string> {
    let venvPath = this.getManagedVenvPath();

    // Ensure global storage exists; fallback to workspace storage on failure
    try {
      if (!fs.existsSync(this.context.globalStorageUri.fsPath)) {
        fs.mkdirSync(this.context.globalStorageUri.fsPath, { recursive: true });
      }
    } catch (err) {
      console.warn('globalStorageUri not writable, falling back to workspace storage', err);
      vscode.window.showWarningMessage('Unable to use global storage. Using workspace storage for managed environment.');
      if (!this.context.storageUri) {
        const msg = 'Unable to access extension storage to create managed environment.';
        vscode.window.showErrorMessage(msg, 'Show Help').then(choice => {
          if (choice === 'Show Help') {
            vscode.env.openExternal(vscode.Uri.parse('https://code.visualstudio.com/docs/editor/settings-sync'));
          }
        });
        throw new Error(msg);
      }
      venvPath = path.join(this.context.storageUri.fsPath, 'mcp-venv');
      if (!fs.existsSync(this.context.storageUri.fsPath)) {
        fs.mkdirSync(this.context.storageUri.fsPath, { recursive: true });
      }
    }

    // Idempotency: if venv exists, validate
    const pythonExe = this.pythonExeForVenv(venvPath);
    if (fs.existsSync(pythonExe)) {
      const choice = await vscode.window.showQuickPick(['Use existing', 'Recreate', 'Upgrade'], { 
        placeHolder: 'A managed environment already exists',
        ignoreFocusOut: true 
      });
      if (!choice) {
        throw new Error('Operation cancelled by user');
      }

      if (choice === 'Recreate') {
        // Remove and recreate
        await vscode.window.withProgress({ 
          location: vscode.ProgressLocation.Notification, 
          title: 'Recreating managed environment...', 
          cancellable: false 
        }, async (progress) => {
          try {
            fs.rmSync(venvPath, { recursive: true, force: true });
            progress.report({ message: 'Creating new virtual environment...' });
            await this.runShellCommand(await this.findBasePython(), ['-m', 'venv', venvPath]);
          } catch (e) {
            const msg = `Failed to recreate environment: ${e instanceof Error ? e.message : String(e)}`;
            vscode.window.showErrorMessage(msg, 'Show Logs').then(choice => {
              if (choice === 'Show Logs') {
                vscode.commands.executeCommand('mcp-jupyter.showServerLogs');
              }
            });
            throw new Error(msg);
          }
        });
      } else if (choice === 'Upgrade') {
        // No structural change; we'll just return the path and let install handle upgrades
        return venvPath;
      } else {
        return venvPath;
      }
    } else {
      // Create venv
      await vscode.window.withProgress({ 
        location: vscode.ProgressLocation.Notification, 
        title: 'Creating Isolated Environment...', 
        cancellable: false 
      }, async (progress) => {
        try {
          const basePython = await this.findBasePython();
          progress.report({ message: 'Setting up virtual environment...' });
          await this.runShellCommand(basePython, ['-m', 'venv', venvPath]);
        } catch (e) {
          const msg = `Failed to create environment: ${e instanceof Error ? e.message : String(e)}`;
          vscode.window.showErrorMessage(msg, 'Show Logs').then(choice => {
            if (choice === 'Show Logs') {
              vscode.commands.executeCommand('mcp-jupyter.showServerLogs');
            }
          });
          throw new Error(msg);
        }
      });
    }

    // Save this preference in global config
    const pythonPath = this.pythonExeForVenv(venvPath);
    await vscode.workspace.getConfiguration('mcp-jupyter').update('pythonPath', pythonPath, vscode.ConfigurationTarget.Global);
    return venvPath;
  }

  async installDependencies(venvPath: string): Promise<void> {
    const pythonExe = this.pythonExeForVenv(venvPath);
    const serverSource = path.join(this.context.extensionPath, 'python_server');
    const wheelsDir = path.join(this.context.extensionPath, 'python_server', 'wheels');
    
    const hasLocalWheels = fs.existsSync(wheelsDir) && fs.readdirSync(wheelsDir).length > 0;

    // Show progress notification
    await vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification,
      title: hasLocalWheels ? 'Installing MCP Server Dependencies (Offline Mode)' : 'Installing MCP Server Dependencies',
      cancellable: false
    }, async (progress) => {
      const terminal = vscode.window.createTerminal('MCP Installer');
      terminal.show();

      progress.report({ message: 'Upgrading pip...' });
      terminal.sendText(`"${pythonExe}" -m pip install --upgrade pip`);
      
      // Wait a bit for pip upgrade
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      progress.report({ message: hasLocalWheels ? 'Installing from bundled wheels...' : 'Downloading from PyPI...' });
      
      if (hasLocalWheels) {
        // Fat VSIX Mode: Install from bundled wheels (offline)
        // --no-index: Don't check PyPI
        // --find-links: Look in the wheels directory for packages
        terminal.sendText(`"${pythonExe}" -m pip install --no-index --find-links="${wheelsDir}" "${serverSource}"`);
        progress.report({ message: 'Using bundled dependencies (offline install)' });
      } else {
        // Standard Online Mode: Download from PyPI
        terminal.sendText(`"${pythonExe}" -m pip install "${serverSource}"`);
      }
      
      // Wait for installation to complete
      await new Promise(resolve => setTimeout(resolve, 5000));
    });

    // Mark setup as complete in global state so walkthrough doesn't run again
    await this.context.globalState.update('mcp.hasCompletedSetup', true);
    
    const installMode = hasLocalWheels ? ' (offline install)' : '';
    vscode.window.showInformationMessage(
      `MCP server dependencies installed successfully${installMode}`,
      'Test Connection'
    ).then(choice => {
      if (choice === 'Test Connection') {
        vscode.commands.executeCommand('mcp-jupyter.testConnection');
      }
    });
  }

  private runShellCommand(command: string, args: string[]): Promise<void> {
    return new Promise((resolve, reject) => {
      const proc = spawn(command, args, { stdio: 'ignore' });
      proc.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`Exit code ${code}`))));
      proc.on('error', (err) => reject(err));
    });
  }

  private async findBasePython(): Promise<string> {
    const candidates = process.platform === 'win32' ? ['py', 'python', 'python3'] : ['python3', 'python'];
    for (const c of candidates) {
      try {
        // Try spawnSync to quickly check for executable
        const check = spawn(c, ['--version']);
        await new Promise<void>((resolve, reject) => {
          let handled = false;
          check.on('error', () => {
            if (!handled) { handled = true; reject(new Error('not found')); }
          });
          check.on('close', (code) => {
            if (!handled) {
              handled = true;
              if (code === 0) resolve(); else reject(new Error('nonzero'));
            }
          });
        });
        return c;
      } catch {
        // try next candidate
      }
    }

    const install = await vscode.window.showErrorMessage(
      'No system Python found. Install the Python extension or download Python from python.org?', 
      'Open Python Extension', 
      'Open python.org',
      'Show Help'
    );
    if (install === 'Open Python Extension') {
      vscode.commands.executeCommand('extension.open', 'ms-python.python');
    } else if (install === 'Open python.org') {
      vscode.env.openExternal(vscode.Uri.parse('https://www.python.org/downloads/'));
    } else if (install === 'Show Help') {
      vscode.env.openExternal(vscode.Uri.parse('https://code.visualstudio.com/docs/python/python-tutorial'));
    }
    throw new Error('No base Python available');
  }
}
