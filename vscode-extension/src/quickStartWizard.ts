import * as vscode from 'vscode';
import { exec } from 'child_process';
import * as fs from 'fs';

import { SetupManager } from './setupManager';
import { McpClient } from './mcpClient';
import { SetupWebview } from './SetupWebview';
import { openTestNotebook } from './notebookUtils';
import { SilentInstaller } from './SilentInstaller';

/**
 * Manages the interactive setup wizard for MCP Jupyter.
 */
export class QuickStartWizard {
    private statusBarItem: vscode.StatusBarItem;
    private setupWebview: SetupWebview;
    private silentInstaller: SilentInstaller;

    constructor(
        private context: vscode.ExtensionContext,
        private setupManager: SetupManager,
        private mcpClient: McpClient
    ) {
        this.setupWebview = new SetupWebview(context, this.runSetup.bind(this));
        this.silentInstaller = new SilentInstaller(context, setupManager, mcpClient);

        this.statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
        this.statusBarItem.command = 'mcp-jupyter.quickStart';
        this.statusBarItem.text = '$(rocket) MCP Jupyter Setup';
        this.statusBarItem.tooltip = 'Set up MCP Jupyter';

        context.subscriptions.push(vscode.commands.registerCommand(
            'mcp-jupyter.validatePythonPath', 
            this.validatePythonPath.bind(this)
        ));
    }

    /**
     * Shows the setup UI if MCP Jupyter has not been configured yet.
     */
    public async showIfNeeded(): Promise<void> {
        const isSetupComplete = this.context.globalState.get('mcp.hasCompletedSetup', false);
        if (isSetupComplete) {
            this.statusBarItem.hide();
            return;
        }

        const silentInstallSuccess = await this.silentInstaller.run();
        if (!silentInstallSuccess) {
            this.statusBarItem.show();
            // If silent install fails, we show the status bar item, which allows the user to manually open the wizard.
            vscode.window.showErrorMessage('MCP Jupyter auto-setup failed.', 'Open Setup').then(choice => {
                if (choice === 'Open Setup') this.show();
            });
        }
    }

    /**
     * Runs the setup process based on the mode selected in the webview.
     */
    public async runSetup(mode: 'managed' | 'existing' | 'remote', data?: any): Promise<void> {
        this.setupWebview.updateStatus(`Starting setup for mode: ${mode}...\n`);
        try {
            // ... (runSetup logic remains the same)

            await this.context.globalState.update('mcp.hasCompletedSetup', true);
            this.setupWebview.updateStatus('\n🎉 MCP Jupyter is ready! You can now close this tab.\n');
            this.hide();
            openTestNotebook(this.context);

        } catch (error) {
            const errorMessage = error instanceof Error ? error.message : String(error);
            this.setupWebview.updateStatus(`\n❌ Setup failed: ${errorMessage}`);
        }
    }

    private async validatePythonPath(pythonPath: string): Promise<boolean> {
        // ... (validation logic is the same)
    }

    public show(): void {
        this.setupWebview.show();
    }

    public hide(): void {
        this.statusBarItem.hide();
    }

    public dispose(): void {
        this.statusBarItem.dispose();
    }
}
