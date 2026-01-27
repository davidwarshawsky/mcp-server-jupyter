import * as vscode from 'vscode';
import { MCPClient } from '../mcpClient';

/**
 * Defines the contract for a self-activating and deactivating feature module.
 */
export interface IFeature {
    activate(context: vscode.ExtensionContext, mcpClient: MCPClient): void;
    deactivate(): void;
}
