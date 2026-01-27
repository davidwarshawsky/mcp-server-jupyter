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

    // Check if Python path is configured
    const pythonPath = vscode.workspace.getConfiguration('python').get('pythonPath') ||
                      vscode.workspace.getConfiguration('python').get('defaultInterpreterPath');
    
    if (!pythonPath) {
        vscode.window.showInformationMessage(
            'MCP Jupyter: Please configure a Python interpreter in VS Code settings.',
            'Open Settings'
        ).then(choice => {
            if (choice === 'Open Settings') {
                vscode.commands.executeCommand('workbench.action.openSettings', 'python.pythonPath');
            }
        });
    }

    // Activate all features
    features.forEach(feature => {
        try {
            feature.activate(context);
        } catch (err) {
            console.error(`Error activating feature: ${err.message}`);
            // Optionally, show a VS Code error message to the user
            // vscode.window.showErrorMessage(`Failed to activate a feature. See console for details.`);
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
