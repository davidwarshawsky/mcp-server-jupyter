import * as vscode from 'vscode';
import { IFeature } from './feature.interface';
import { MCPClient } from '../mcpClient';

export class QuickStartFeature implements IFeature {
    activate(context: vscode.ExtensionContext, mcpClient: MCPClient): void {
        // Placeholder implementation - quickstart functionality moved to core extension
        context.subscriptions.push(
            vscode.commands.registerCommand('mcp-jupyter.quickStart', () => {
                vscode.window.showInformationMessage('MCP Jupyter extension is ready to use!');
            })
        );
    }

    deactivate(): void {
        // Nothing to deactivate
    }
}
