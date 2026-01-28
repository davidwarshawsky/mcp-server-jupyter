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

    // 1. Verify Python Environment
    const pythonExtension = vscode.extensions.getExtension('ms-python.python');
    if (!pythonExtension) {
        vscode.window.showErrorMessage('Python extension is not installed. Please install ms-python.python.');
        return;
    }

    if (!pythonExtension.isActive) await pythonExtension.activate();
    const pythonApi = pythonExtension.exports;
    const pythonPath = pythonApi.settings.getExecutionDetails().execCommand[0];

    if (!pythonPath) {
        vscode.window.showErrorMessage('No Python interpreter selected. Please select one in VS Code.');
        return;
    }

    // 2. Check for MCP Server & Install if missing
    try {
        await execAsync(`"${pythonPath}" -c "import mcp_server_jupyter"`);
    } catch (e) {
        const choice = await vscode.window.showWarningMessage(
            `The "mcp-server-jupyter" package is required in your selected Python environment.\n\nInterpreter: ${pythonPath}`,
            "Install via Pip", "Cancel"
        );

        if (choice === "Install via Pip") {
            await vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: "Installing MCP Server...",
                cancellable: false
            }, async () => {
                // Install from PyPI (or local path for dev)
                await execAsync(`"${pythonPath}" -m pip install mcp-server-jupyter`);
            });
            vscode.window.showInformationMessage("MCP Server installed! Reloading...");
        } else {
            return; // Exit if user declines
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
