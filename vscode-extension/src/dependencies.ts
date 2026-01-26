import * as vscode from 'vscode';
import { spawn } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import { getProxyAwareEnv } from './envUtils';


// Helper: Check Python version is >= 3.10
async function checkPythonVersion(pythonPath: string): Promise<boolean> {
  return new Promise((resolve) => {
    try {
      const proc = spawn(pythonPath, ['--version'], { env: getProxyAwareEnv() });
      let output = '';

      proc.stdout.on('data', (d) => (output += d.toString()));
      proc.stderr.on('data', (d) => (output += d.toString()));

      proc.on('close', () => {
        const match = output.match(/Python (\d+)\.(\d+)/);
        if (match) {
          const major = parseInt(match[1], 10);
          const minor = parseInt(match[2], 10);
          if (major === 3 && minor >= 10) return resolve(true);
        }
        return resolve(false);
      });

      proc.on('error', () => resolve(false));
    } catch (e) {
      return resolve(false);
    }
  });
}

/**
 * Check if Python dependencies are installed
 */
export async function checkPythonDependencies(
  pythonPath: string,
  serverPath: string,
  outputChannel: vscode.OutputChannel
): Promise<boolean> {
  outputChannel.appendLine('Checking Python environment...');

  // Enforce Python version gate (Day 1 Fix)
  outputChannel.appendLine(`Checking Python version for: ${pythonPath}`);
  const isCompatibleVersion = await checkPythonVersion(pythonPath);
  if (!isCompatibleVersion) {
    vscode.window.showErrorMessage(
      `Selected Python is too old. MCP Jupyter requires Python 3.10+. Found: ${pythonPath}`,
      'Select Different Interpreter'
    ).then(val => {
      if (val) vscode.commands.executeCommand('mcp-jupyter.selectEnvironment');
    });
    return false;
  }

  // 1. If we have a source folder, check requirements.txt (Classic Mode)
  if (serverPath && fs.existsSync(path.join(serverPath, 'requirements.txt'))) {
      // Classic check logic could rely on pip freeze, but simple import check below is usually enough
      // For now we trust the import check is verifying what matters
  } else {
      outputChannel.appendLine('ℹ No source directory found. Assuming package is installed in environment.');
  }

  // 2. Critical: Check if we can actually import the server module
  // We check for 'mcp' AND 'src.main' (or the package name, but here we use src.main as our canonical check for the running code)
  const testImports = `
import sys
try:
    import mcp
    import jupyter_client
    # Try to import the server entry point to ensure package is installed
    # If running from source, 'src' is current directory.
    # If installed via pip, 'src' might be part of the package structure if package is poorly named, 
    # BUT usually users install 'mcp-server-jupyter'. 
    # Let's check for 'mcp' and 'jupyter_client' primarily.
    # To really verify our specific server is there, we try 'import src.main' OR check if 'mcp_server_jupyter' is installed?
    # Given the user pip installed current dir, 'src' is strictly inside that layout.
    # Actually, pip install . installs the package 'mcp-server-jupyter'.
    # Because layout is src-based, it might be installed as 'src' if not careful, OR 'mcp_server_jupyter' if pyproject configured right.
    # Looking at pyproject.toml: packages = [{include = "src"}]
    # This usually means top level import is 'src'. 
    # Let's stick to the user provided snippet which checks src.main.
    import src.main 
    print("OK")
except ImportError as e:
    print(f"MISSING: {e}")
    sys.exit(1)
`;

  return new Promise((resolve) => {
    // [SECURITY] Validate pythonPath before execution
    // Prevent command injection if pythonPath is controlled by workspace settings
    if (!pythonPath || typeof pythonPath !== 'string') {
      outputChannel.appendLine('✗ Invalid Python path configuration');
      resolve(false);
      return;
    }

    // Check if pythonPath looks suspicious (contains shell metacharacters)
    const suspiciousChars = /[;&|$`]/;
    if (suspiciousChars.test(pythonPath)) {
      outputChannel.appendLine(
        `✗ SECURITY WARNING: Python path contains suspicious characters: ${pythonPath}`
      );
      outputChannel.appendLine('  This may be a command injection attempt.');
      resolve(false);
      return;
    }

    // Verify pythonPath is an executable file (not a directory or script)
    try {
      const stats = fs.statSync(pythonPath);
      if (!stats.isFile()) {
        outputChannel.appendLine(`✗ Python path is not a file: ${pythonPath}`);
        resolve(false);
        return;
      }
      
      // On Unix, verify it's executable
      if (process.platform !== 'win32') {
        try {
          fs.accessSync(pythonPath, fs.constants.X_OK);
        } catch {
          outputChannel.appendLine(`✗ Python path is not executable: ${pythonPath}`);
          resolve(false);
          return;
        }
      }
    } catch (error) {
      outputChannel.appendLine(`✗ Cannot access Python path: ${pythonPath}`);
      resolve(false);
      return;
    }

    // Only set cwd if we have a valid path, otherwise run from anywhere (testing global site-packages)
    // [DUH FIX #3] Inherit proxy settings for corporate environments
    const spawnOpts = {
      ...(serverPath && { cwd: serverPath }),
      env: getProxyAwareEnv()
    };
    
    const proc = spawn(pythonPath, ['-c', testImports], spawnOpts);

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (data) => {
      stdout += data.toString();
    });

    proc.stderr.on('data', (data) => {
      stderr += data.toString();
    });

    proc.on('close', (code) => {
      if (code === 0 && stdout.trim() === 'OK') {
        outputChannel.appendLine('✓ Environment validated');
        resolve(true);
      } else {
        outputChannel.appendLine('✗ Missing Python dependencies:');
        outputChannel.appendLine(stdout + stderr);
        resolve(false);
      }
    });

    proc.on('error', (error) => {
      outputChannel.appendLine(`✗ Failed to check dependencies: ${error.message}`);
      resolve(false);
    });
  });
}

/**
 * Install Python dependencies
 */
export async function installPythonDependencies(
  pythonPath: string,
  serverPath: string,
  outputChannel: vscode.OutputChannel
): Promise<boolean> {
  const requirementsPath = path.join(serverPath, 'requirements.txt');

  if (!fs.existsSync(requirementsPath)) {
    vscode.window.showErrorMessage('requirements.txt not found in server directory');
    return false;
  }

  outputChannel.appendLine('Installing Python dependencies...');
  outputChannel.show();

  return new Promise((resolve) => {
    // [DUH FIX #3] Inherit proxy settings for corporate environments (Zscaler, etc.)
    const proc = spawn(pythonPath, ['-m', 'pip', 'install', '-r', 'requirements.txt'], {
      cwd: serverPath,
      env: getProxyAwareEnv()
    });

    proc.stdout.on('data', (data) => {
      outputChannel.append(data.toString());
    });

    proc.stderr.on('data', (data) => {
      outputChannel.append(data.toString());
    });

    proc.on('close', (code) => {
      if (code === 0) {
        outputChannel.appendLine('✓ Dependencies installed successfully');
        resolve(true);
      } else {
        outputChannel.appendLine(`✗ Failed to install dependencies (exit code: ${code})`);
        resolve(false);
      }
    });

    proc.on('error', (error) => {
      outputChannel.appendLine(`✗ Failed to install dependencies: ${error.message}`);
      resolve(false);
    });
  });
}

/**
 * Prompt user to install dependencies
 */
export async function promptInstallDependencies(
  pythonPath: string,
  serverPath: string,
  outputChannel: vscode.OutputChannel
): Promise<boolean> {
  const choice = await vscode.window.showWarningMessage(
    'MCP Agent Kernel requires Python dependencies (mcp, jupyter_client, nbformat, psutil). Install now?',
    'Install',
    'Cancel',
    'Show Requirements'
  );

  if (choice === 'Show Requirements') {
    const requirementsPath = path.join(serverPath, 'requirements.txt');
    if (fs.existsSync(requirementsPath)) {
      const doc = await vscode.workspace.openTextDocument(requirementsPath);
      await vscode.window.showTextDocument(doc);
    }
    return false;
  }

  if (choice === 'Install') {
    return await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Installing Python dependencies...',
        cancellable: false,
      },
      async () => {
        return await installPythonDependencies(pythonPath, serverPath, outputChannel);
      }
    );
  }

  return false;
}
