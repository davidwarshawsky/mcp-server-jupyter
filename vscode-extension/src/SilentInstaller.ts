import * as vscode from 'vscode';
import { SetupManager } from './setupManager';
import { McpClient } from './mcpClient';
import { openTestNotebook } from './notebookUtils';

/**
 * Handles the silent, automatic installation of MCP Jupyter in the background.
 */
export class SilentInstaller {
    private isAutoInstalling = false;

    constructor(
        private context: vscode.ExtensionContext,
        private setupManager: SetupManager,
        private mcpClient: McpClient
    ) {}

    public async run(): Promise<boolean> {
        if (this.isAutoInstalling) {
            return true; // Already running
        }

        const alreadyAttempted = this.context.workspaceState.get('mcp.autoInstallAttempted', false);
        if (alreadyAttempted) {
            return false; // Already attempted, let the user manually trigger setup.
        }

        this.isAutoInstalling = true;
        await this.context.workspaceState.update('mcp.autoInstallAttempted', true);
        const statusMessage = vscode.window.setStatusBarMessage('$(sync~spin) Installing MCP Jupyter...');

        try {
            const venvPath = await this.setupManager.createManagedEnvironmentSilent();
            await this.setupManager.installDependenciesSilent(venvPath);
            await this.mcpClient.start();
            await this.context.globalState.update('mcp.hasCompletedSetup', true);
            
            statusMessage.dispose();
            vscode.window.showInformationMessage('✅ MCP Jupyter Ready! Select "MCP Kernel" to start.', 'Open Example Notebook').then(choice => {
                if (choice === 'Open Example Notebook') {
                    openTestNotebook(this.context);
                }
            });
            return true;
        } catch (error) {
            statusMessage.dispose();
            this.isAutoInstalling = false;
            // The quickstart wizard will show the error and offer to open the setup.
            return false;
        } finally {
            this.isAutoInstalling = false;
        }
    }
}
