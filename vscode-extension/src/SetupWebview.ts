import * as vscode from 'vscode';
import * as path from 'path';

/**
 * Manages the webview panel for the MCP Jupyter setup wizard.
 * This provides a rich, interactive UI for guiding users through the installation process.
 */
export class SetupWebview {
    private panel: vscode.WebviewPanel | undefined;
    private readonly context: vscode.ExtensionContext;

    constructor(context: vscode.ExtensionContext) {
        this.context = context;
    }

    /**
     * Creates or reveals the setup webview panel.
     */
    public show(): void {
        if (this.panel) {
            this.panel.reveal(vscode.ViewColumn.One);
        } else {
            this.panel = vscode.window.createWebviewPanel(
                'mcpJupyterSetup', // Identifies the type of the webview. Used internally
                'MCP Jupyter Setup', // Title of the panel displayed to the user
                vscode.ViewColumn.One, // Editor column to show the new webview panel in.
                {
                    enableScripts: true, // Allow scripts to run in the webview
                    localResourceRoots: [vscode.Uri.file(path.join(this.context.extensionPath, 'media'))]
                }
            );

            this.panel.webview.html = this.getWebviewContent();

            this.panel.onDidDispose(() => {
                this.panel = undefined;
            }, null, this.context.subscriptions);
        }
    }

    /**
     * Generates the HTML content for the webview.
     */
    private getWebviewContent(): string {
        // For now, this is a placeholder. We will add the actual HTML structure later.
        return `<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>MCP Jupyter Setup</title>
            </head>
            <body>
                <h1>Welcome to MCP Jupyter Setup</h1>
                <p>Interactive setup wizard coming soon!</p>
            </body>
            </html>`;
    }
}
