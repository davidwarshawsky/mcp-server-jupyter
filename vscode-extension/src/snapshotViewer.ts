import * as vscode from 'vscode';
import { DatabaseService, ISnapshot, ISnapshotVariable } from './database';

export class SnapshotViewer {
    constructor(private databaseService: DatabaseService) {}

    public async viewSnapshot(snapshot: ISnapshot): Promise<void> {
        const panel = vscode.window.createWebviewPanel(
            'snapshotViewer',
            `Snapshot: ${snapshot.name}`,
            vscode.ViewColumn.One,
            { enableScripts: true }
        );

        const variables = await this.databaseService.getVariablesForSnapshot(snapshot.id);
        panel.webview.html = this.getHtmlForWebview(snapshot, variables);
    }

    private getHtmlForWebview(snapshot: ISnapshot, variables: ISnapshotVariable[]): string {
        const variableRows = variables.map(v => `
            <tr>
                <td>${v.name}</td>
                <td>${v.type}</td>
                <td>${v.preview}</td>
                <td>${new Date(v.timestamp * 1000).toLocaleString()}</td>
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
                <p><strong>Notebook:</strong> ${snapshot.notebookPath}</p>
                <p><strong>Created:</strong> ${new Date(snapshot.createdAt * 1000).toLocaleString()}</p>
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
