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

    // [FRICTION FIX #3] Run pip silently in background - terminal scares non-developers
    // Only show terminal on error
    const result: { error: Error | null } = { error: null };

    await vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification,
      title: '\ud83d\ude80 Setting up MCP Jupyter',
      cancellable: false
    }, async (progress) => {
      try {
        // Step 1: Upgrade pip (silently)
        progress.report({ increment: 10, message: 'Preparing environment...' });
        await this.runPipCommand(pythonExe, ['install', '--upgrade', 'pip', '--quiet']);
        
        // Step 2: Install dependencies (silently)
        progress.report({ increment: 30, message: hasLocalWheels ? 'Installing (offline)...' : 'Downloading packages...' });
        
        if (hasLocalWheels) {
          // Fat VSIX Mode: Install from bundled wheels (offline)
          await this.runPipCommand(pythonExe, [
            'install', '--no-index', 
            `--find-links=${wheelsDir}`, 
            serverSource,
            '--quiet'
          ]);
        } else {
          // Standard Online Mode: Download from PyPI
          await this.runPipCommand(pythonExe, ['install', serverSource, '--quiet']);
        }
        
        progress.report({ increment: 50, message: 'Finalizing...' });
        await new Promise(resolve => setTimeout(resolve, 500));
        
        progress.report({ increment: 10, message: 'Done!' });
      } catch (error) {
        result.error = error instanceof Error ? error : new Error(String(error));
      }
    });

    // [FRICTION FIX #3] Only show terminal on error for debugging
    if (result.error) {
      const errorMessage = result.error.message;
      const choice = await vscode.window.showErrorMessage(
        `Installation failed: ${errorMessage}`,
        'Show Details',
        'Retry',
        'Get Help'
      );
      
      if (choice === 'Show Details') {
        // Now show terminal for debugging
        const terminal = vscode.window.createTerminal('MCP Installer (Debug)');
        terminal.show();
        terminal.sendText(`echo "Retrying installation with verbose output..."`);
        terminal.sendText(`"${pythonExe}" -m pip install "${serverSource}" --verbose`);
      } else if (choice === 'Retry') {
        return this.installDependencies(venvPath);
      } else if (choice === 'Get Help') {
        vscode.env.openExternal(vscode.Uri.parse('https://github.com/example/mcp-jupyter/issues'));
      }
      throw result.error;
    }

    // Mark setup as complete in global state
    await this.context.globalState.update('mcp.hasCompletedSetup', true);
    
    const installMode = hasLocalWheels ? ' (offline install)' : '';
    vscode.window.showInformationMessage(
      `\u2705 MCP Jupyter is ready${installMode}!`,
      'Test Connection'
    ).then(choice => {
      if (choice === 'Test Connection') {
        vscode.commands.executeCommand('mcp-jupyter.testConnection');
      }
    });
  }

  /**
   * [FRICTION FIX #3] Run pip command silently in background
   * No scary terminal output for non-developers
   */
  private runPipCommand(pythonExe: string, args: string[]): Promise<string> {
    return new Promise((resolve, reject) => {
      const proc = spawn(pythonExe, ['-m', 'pip', ...args], {
        stdio: ['pipe', 'pipe', 'pipe']
      });
      
      let stdout = '';
      let stderr = '';
      
      proc.stdout?.on('data', (data) => { stdout += data.toString(); });
      proc.stderr?.on('data', (data) => { stderr += data.toString(); });
      
      proc.on('close', (code) => {
        if (code === 0) {
          resolve(stdout);
        } else {
          reject(new Error(`pip exited with code ${code}: ${stderr || stdout}`));
        }
      });
      
      proc.on('error', (err) => reject(err));
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

  // ============================================================================
  // [DS UX FIX] Silent methods for zero-friction "Invisible Setup"
  // These run without any UI prompts - only notify on success/failure
  // ============================================================================

  /**
   * Create managed environment silently (no prompts, no progress dialogs)
   */
  async createManagedEnvironmentSilent(): Promise<string> {
    let venvPath = this.getManagedVenvPath();

    // Ensure global storage exists
    try {
      if (!fs.existsSync(this.context.globalStorageUri.fsPath)) {
        fs.mkdirSync(this.context.globalStorageUri.fsPath, { recursive: true });
      }
    } catch {
      // Fall back to workspace storage
      if (!this.context.storageUri) {
        throw new Error('Unable to access extension storage');
      }
      venvPath = path.join(this.context.storageUri.fsPath, 'mcp-venv');
      if (!fs.existsSync(this.context.storageUri.fsPath)) {
        fs.mkdirSync(this.context.storageUri.fsPath, { recursive: true });
      }
    }

    // If venv already exists, just use it (no prompts)
    const pythonExe = this.pythonExeForVenv(venvPath);
    if (fs.existsSync(pythonExe)) {
      // Save config and return existing venv
      await vscode.workspace.getConfiguration('mcp-jupyter').update(
        'pythonPath', pythonExe, vscode.ConfigurationTarget.Global
      );
      return venvPath;
    }

    // Create venv silently
    const basePython = await this.findBasePythonSilent();
    await this.runShellCommand(basePython, ['-m', 'venv', venvPath]);

    // Save config
    await vscode.workspace.getConfiguration('mcp-jupyter').update(
      'pythonPath', pythonExe, vscode.ConfigurationTarget.Global
    );
    return venvPath;
  }

  /**
   * Install dependencies silently (no terminal, no prompts)
   */
  async installDependenciesSilent(venvPath: string): Promise<void> {
    const pythonExe = this.pythonExeForVenv(venvPath);
    const serverSource = path.join(this.context.extensionPath, 'python_server');
    const wheelsDir = path.join(this.context.extensionPath, 'python_server', 'wheels');
    
    const hasLocalWheels = fs.existsSync(wheelsDir) && fs.readdirSync(wheelsDir).length > 0;

    // Upgrade pip silently
    await this.runPipCommand(pythonExe, ['install', '--upgrade', 'pip', '--quiet']);
    
    // Install dependencies silently
    if (hasLocalWheels) {
      await this.runPipCommand(pythonExe, [
        'install', '--no-index', 
        `--find-links=${wheelsDir}`, 
        serverSource,
        '--quiet'
      ]);
    } else {
      await this.runPipCommand(pythonExe, ['install', serverSource, '--quiet']);
    }

    // Mark setup as complete
    await this.context.globalState.update('mcp.hasCompletedSetup', true);
  }

  /**
   * Find base Python without prompts (for silent install)
   */
  private async findBasePythonSilent(): Promise<string> {
    const candidates = process.platform === 'win32' 
      ? ['py', 'python', 'python3'] 
      : ['python3', 'python'];
    
    for (const c of candidates) {
      try {
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
    throw new Error('No Python found. Install Python 3.9+ from python.org');
  }
}
