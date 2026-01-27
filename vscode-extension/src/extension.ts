import * as vscode from 'vscode';
import { McpClient } from './mcpClient';
import { MCPKernel } from './mcpKernel';
import { SetupManager } from './setupManager';
import { QuickStartWizard } from './quickStartWizard';

let quickStartWizard: QuickStartWizard;

export function activate(context: vscode.ExtensionContext) {
    console.log('Congratulations, your extension "mcp-jupyter" is now active!');

    // Initialize the core components
    const setupManager = new SetupManager(context);
    const mcpClient = McpClient.getInstance('ws://localhost:8888', 'test-session', new MCPKernel());
    quickStartWizard = new QuickStartWizard(context, setupManager, mcpClient);

    // Register the main command for the quick start wizard
    const quickStartCommand = vscode.commands.registerCommand('mcp-jupyter.quickStart', () => {
        quickStartWizard.show();
    });

    context.subscriptions.push(quickStartCommand);

    // Automatically show the wizard if setup has not been completed
    quickStartWizard.showIfNeeded();

    // Register the kernel
    context.subscriptions.push(
        vscode.notebook.registerNotebookKernelProvider(
            { viewType: 'mcp-jupyter-notebook' },
            {
                provideKernels: async () => {
                    // Check if setup is complete before providing the kernel
                    const isSetupComplete = context.globalState.get('mcp.hasCompletedSetup', false);
                    if (isSetupComplete) {
                        return [new MCPKernel()];
                    }
                    return [];
                }
            }
        )
    );
}

export function deactivate() {
    if (quickStartWizard) {
        quickStartWizard.dispose();
    }
}
