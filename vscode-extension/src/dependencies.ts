import * as vscode from 'vscode';
import { spawn } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

/**
 * Check if Python dependencies are installed
 */
export async function checkPythonDependencies(
  pythonPath: string,
  serverPath: string,
  outputChannel: vscode.OutputChannel
): Promise<boolean> {
  outputChannel.appendLine('Checking Python dependencies...');

  // Check if requirements.txt exists
  const requirementsPath = path.join(serverPath, 'requirements.txt');
  if (!fs.existsSync(requirementsPath)) {
    outputChannel.appendLine('⚠ No requirements.txt found, assuming dependencies are installed');
    return true;
  }

  // Try to import key modules
  const testImports = `
import sys
try:
    import mcp
    import jupyter_client
    import nbformat
    import psutil
    print("OK")
except ImportError as e:
    print(f"MISSING: {e}")
    sys.exit(1)
`;

  return new Promise((resolve) => {
    const proc = spawn(pythonPath, ['-c', testImports], {
      cwd: serverPath,
    });

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
        outputChannel.appendLine('✓ All Python dependencies are installed');
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
    const proc = spawn(pythonPath, ['-m', 'pip', 'install', '-r', 'requirements.txt'], {
      cwd: serverPath,
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
