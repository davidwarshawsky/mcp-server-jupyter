import * as vscode from 'vscode';
import { MCPClient } from './mcpClient';

export class SyncCodeLensProvider implements vscode.CodeLensProvider {
  private _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
  public readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;
  private notebookSyncStatus = new Map<string, boolean>();

  constructor(private mcpClient: MCPClient) {}

  public setSyncNeeded(notebookPath: string, needed: boolean): void {
    this.notebookSyncStatus.set(notebookPath, needed);
    this._onDidChangeCodeLenses.fire();
  }

  public refresh(): void {
    this._onDidChangeCodeLenses.fire();
  }

  public provideCodeLenses(
    document: vscode.TextDocument,
    token: vscode.CancellationToken
  ): vscode.CodeLens[] | Thenable<vscode.CodeLens[]> {
    // Only provide code lenses for notebook files
    if (!document.uri.fsPath.endsWith('.ipynb')) {
      return [];
    }

    const syncNeeded = this.notebookSyncStatus.get(document.uri.fsPath) || false;
    const range = new vscode.Range(0, 0, 0, 0);

    if (syncNeeded) {
      return [
        new vscode.CodeLens(range, {
          title: '$(alert) MCP: Out of Sync (Click to Fix)',
          tooltip: 'The notebook file on disk has changed. Click to sync the kernel state.',
          command: 'mcp-jupyter.syncNotebook',
          arguments: [document.uri.fsPath]
        })
      ];
    } else {
      return [
        new vscode.CodeLens(range, {
          title: '$(sync) MCP: Synced',
          tooltip: 'The notebook is in sync with the kernel state',
          command: ''
        })
      ];
    }
  }

  public resolveCodeLens(
    codeLens: vscode.CodeLens,
    token: vscode.CancellationToken
  ): vscode.CodeLens {
    return codeLens;
  }
}
