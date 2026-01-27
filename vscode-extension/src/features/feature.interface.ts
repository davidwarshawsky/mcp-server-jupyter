import * as vscode from 'vscode';

/**
 * Defines the contract for a self-activating and deactivating feature module.
 */
export interface IFeature {
    activate(context: vscode.ExtensionContext): void;
    deactivate(): void;
}
