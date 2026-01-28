import * as vscode from 'vscode';
import { exec } from 'child_process';
import { promisify } from 'util';
import { MCPClient } from './mcpClient';
import { IFeature } from './features/feature.interface';
import { SnapshotFeature } from './features/snapshot.feature';

// A list of all active features in the extension.
// To add a new feature, simply create its class implementing IFeature and add it to this list.
const features: IFeature[] = [
    new SnapshotFeature(),
];

/**
 * This is the main entry point of the extension.
 * It orchestrates the activation of all registered features.
 */
export async function activate(context: vscode.ExtensionContext) {
    console.log('Congratulations, your extension "mcp-jupyter" is now active!');

    const execAsync = promisify(exec);

    // 1. Get the Active Interpreter
    const pythonExt = vscode.extensions.getExtension('ms-python.python');
    if (!pythonExt) return;
    if (!pythonExt.isActive) await pythonExt.activate();
    
    // Get the path the user has ALREADY selected for this notebook
    const pythonPath = pythonExt.exports.settings.getExecutionDetails().execCommand?.[0];
    if (!pythonPath) return;

    // 2. Silent Check & Noisy Fix
    try {
        await execAsync(`"${pythonPath}" -c "import mcp_server_jupyter"`);
    } catch {
        const choice = await vscode.window.showWarningMessage(
            "The MCP features require a helper package in your Python environment.",
            "Install Helper", "Ignore"
        );
        if (choice === "Install Helper") {
            await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Installing..." }, async () => {
                await execAsync(`"${pythonPath}" -m pip install mcp-server-jupyter`);
            });
            vscode.commands.executeCommand('workbench.action.reloadWindow');
        }
    }

    // 3. Start Client
    const sessionId = 'vscode-session-' + Date.now();
    const mcpClient = MCPClient.getInstance(pythonPath, sessionId);

    // Activate features
    features.forEach(feature => {
        try {
            feature.activate(context, mcpClient);
        } catch (err) {
            console.error(`Error activating feature: ${err.message}`);
        }
    });
}

/**
 * This is the main exit point of the extension.
 * It orchestrates the deactivation of all registered features.
 */
export function deactivate() {
    // Deactivate all features in reverse order
    features.slice().reverse().forEach(feature => {
        try {
            feature.deactivate();
        } catch (err) {
            console.error(`Error deactivating feature: ${err.message}`);
        }
    });
}
