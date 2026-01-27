import * as vscode from 'vscode';
import { IFeature } from './feature.interface';
import { QuickStartWizard } from '../quickStartWizard';
import { SetupManager } from '../setupManager';
import { McpClient } from '../mcpClient';
import { MCPKernel } from '../mcpKernel';

export class QuickStartFeature implements IFeature {
    private quickStartWizard: QuickStartWizard | undefined;

    activate(context: vscode.ExtensionContext): void {
        const setupManager = new SetupManager(context);
        // Note: The MCPClient and Kernel are part of this feature for now.
        // In a more advanced architecture, they might become their own core service.
        const mcpClient = McpClient.getInstance('ws://localhost:8888', 'test-session', new MCPKernel());
        this.quickStartWizard = new QuickStartWizard(context, setupManager, mcpClient);

        context.subscriptions.push(
            vscode.commands.registerCommand('mcp-jupyter.quickStart', () => {
                if (this.quickStartWizard) {
                    this.quickStartWizard.show();
                }
            })
        );

        // Automatically show the wizard if setup has not been completed
        if (this.quickStartWizard) {
            this.quickStartWizard.showIfNeeded();
        }

        // Register the kernel provider, which depends on the setup state
        context.subscriptions.push(
            vscode.notebook.registerNotebookKernelProvider(
                { viewType: 'mcp-jupyter-notebook' },
                {
                    provideKernels: async () => {
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

    deactivate(): void {
        if (this.quickStartWizard) {
            this.quickStartWizard.dispose();
        }
    }
}
