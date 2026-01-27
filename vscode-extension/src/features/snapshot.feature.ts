import * as vscode from 'vscode';
import * as path from 'path';
import { IFeature } from './feature.interface';
import { DatabaseManager } from '../databaseManager';
import { SnapshotTreeDataProvider } from '../snapshotTreeDataProvider';
import { SnapshotViewer } from '../snapshotViewer';

export class SnapshotFeature implements IFeature {
    private dbManager: DatabaseManager | undefined;

    activate(context: vscode.ExtensionContext, mcpClient: any): void {
        this.dbManager = new DatabaseManager();
        const snapshotTreeDataProvider = new SnapshotTreeDataProvider(this.dbManager);
        const snapshotViewer = new SnapshotViewer(this.dbManager);

        vscode.window.registerTreeDataProvider('mcp-jupyter-snapshots', snapshotTreeDataProvider);

        const updateActiveWorkspace = () => {
            if (!this.dbManager) return;
            let activeWorkspace: vscode.WorkspaceFolder | undefined;
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                activeWorkspace = vscode.workspace.getWorkspaceFolder(editor.document.uri);
            } else {
                activeWorkspace = vscode.workspace.workspaceFolders?.[0];
            }
            this.dbManager.setActiveWorkspace(activeWorkspace);
            snapshotTreeDataProvider.refresh();
        };

        context.subscriptions.push(
            vscode.window.onDidChangeActiveTextEditor(() => updateActiveWorkspace()),
            vscode.workspace.onDidChangeWorkspaceFolders(() => updateActiveWorkspace())
        );
        updateActiveWorkspace(); // Initial call

        context.subscriptions.push(
            vscode.commands.registerCommand('mcp-jupyter.viewSnapshot', (snapshot) => snapshotViewer.viewSnapshot(snapshot)),
            vscode.commands.registerCommand('mcp-jupyter.saveSnapshot', async () => {
                if (!this.dbManager) return;
                const dbService = await this.dbManager.getActiveService();
                const activeWorkspace = vscode.workspace.workspaceFolders?.[0]; // Simplified
                if (!dbService || !activeWorkspace) {
                    vscode.window.showErrorMessage('Cannot save snapshot. No active workspace or database.');
                    return;
                }

                const snapshotName = await vscode.window.showInputBox({ prompt: 'Enter a name for the snapshot' });
                if (snapshotName) {
                    const editor = vscode.window.activeNotebookEditor;
                    if (!editor) {
                        vscode.window.showErrorMessage('No active notebook to snapshot.');
                        return;
                    }
                    const notebookPath = editor.notebook.uri.fsPath;
                    const relativePath = path.relative(activeWorkspace.uri.fsPath, notebookPath);

                    const dummyVariables = [
                        { name: 'df', type: 'DataFrame', preview: '[100 rows x 5 cols]', timestamp: Math.floor(Date.now() / 1000) },
                        { name: 'x', type: 'int', preview: '42', timestamp: Math.floor(Date.now() / 1000) }
                    ];

                    await dbService.saveSnapshot(snapshotName, relativePath, dummyVariables);
                    snapshotTreeDataProvider.refresh();
                }
            }),
            vscode.commands.registerCommand('mcp-jupyter.clearSnapshots', async () => {
                if (!this.dbManager) return;
                const dbService = await this.dbManager.getActiveService();
                if (!dbService) {
                    vscode.window.showErrorMessage('No active database to clear.');
                    return;
                }
                await dbService.clearAllSnapshots();
                snapshotTreeDataProvider.refresh();
            })
        );
    }

    deactivate(): void {
        if (this.dbManager) {
            this.dbManager.closeAll();
        }
    }
}
