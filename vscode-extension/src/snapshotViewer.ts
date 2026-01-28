import * as vscode from 'vscode';
import { DatabaseManager } from './databaseManager';
import { ISnapshot, ISnapshotVariable } from './database';

export class SnapshotViewer {
    constructor(private dbManager: DatabaseManager) {}

    public async viewSnapshot(snapshot: ISnapshot): Promise<void> {
        const dbService = await this.dbManager.getActiveService();
        if (!dbService) {
            vscode.window.showErrorMessage('Cannot view snapshot. No active workspace database.');
            return;
        }

        const panel = vscode.window.createWebviewPanel(
            'snapshotViewer',
            `Snapshot: ${snapshot.name}`,
            vscode.ViewColumn.One,
            { enableScripts: true }
        );

        const variables = await dbService.getVariablesForSnapshot(snapshot.id);
        panel.webview.html = this.getHtmlForWebview(snapshot, variables);
    }

    // ... (getHtmlForWebview remains the same)
    private getHtmlForWebview(snapshot: ISnapshot, variables: ISnapshotVariable[]): string {
        const variableRows = variables.map(v => `
            <tr>
                <td>${v.var_name}</td>
                <td>${v.var_type}</td>
                <td>${v.var_value}</td>
                <td>N/A</td>
            </tr>
        `).join('');

        return `
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Snapshot: ${snapshot.name}</title>
                <style>
                    /* Add some basic styling */
                    table {
                        width: 100%;
                        border-collapse: collapse;
                    }
                    th, td {
                        border: 1px solid #ddd;
                        padding: 8px;
                        text-align: left;
                    }
                    th {
                        background-color: #f2f2f2;
                    }
                </style>
            </head>
            <body>
                <h1>Snapshot: ${snapshot.name}</h1>
                <p><strong>Notebook:</strong> ${snapshot.notebook_path}</p>
                <p><strong>Created:</strong> ${new Date(parseInt(snapshot.created_at) * 1000).toLocaleString()}</p>
                <table>
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Type</th>
                            <th>Preview</th>
                            <th>Timestamp</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${variableRows}
                    </tbody>
                </table>
            </body>
            </html>
        `;
    }
}
