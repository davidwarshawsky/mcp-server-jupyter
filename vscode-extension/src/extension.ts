import * as vscode from 'vscode';
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
export function activate(context: vscode.ExtensionContext) {
    console.log('Congratulations, your extension "mcp-jupyter" is now active!');

    // Get the active Python interpreter
    const pythonExtension = vscode.extensions.getExtension('ms-python.python');
    if (!pythonExtension) {
        vscode.window.showErrorMessage('Python extension is not installed. Please install ms-python.python.');
        return;
    }

    const pythonApi = pythonExtension.exports;
    const pythonPath = pythonApi.settings.getExecutionDetails().execCommand[0];

    if (!pythonPath) {
        vscode.window.showInformationMessage(
            'MCP Jupyter: Please configure a Python interpreter in VS Code settings.',
            'Open Settings'
        ).then(choice => {
            if (choice === 'Open Settings') {
                vscode.commands.executeCommand('workbench.action.openSettings', 'python.pythonPath');
            }
        });
        return;
    }

    // Check if mcp-server-jupyter is installed
    const terminal = vscode.window.createTerminal('MCP Check');
    terminal.sendText(`${pythonPath} -c "import mcp_server_jupyter"`);
    terminal.sendText('exit');
    
    // For now, assume it's installed or prompt
    // TODO: Add proper check and install prompt

    // Create MCP client with stdio
    const sessionId = 'vscode-session';
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
