import * as vscode from 'vscode';
import { DatabaseManager } from './databaseManager';
import { ISnapshot } from './database';

export class SnapshotTreeDataProvider implements vscode.TreeDataProvider<SnapshotTreeItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<SnapshotTreeItem | undefined | null | void> = new vscode.EventEmitter<SnapshotTreeItem | undefined | null | void>();
    readonly onDidChangeTreeData: vscode.Event<SnapshotTreeItem | undefined | null | void> = this._onDidChangeTreeData.event;

    constructor(private dbManager: DatabaseManager) {}

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element: SnapshotTreeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: SnapshotTreeItem): Promise<SnapshotTreeItem[]> {
        if (element) {
            return [];
        }

        const dbService = await this.dbManager.getActiveService();
        if (!dbService || !dbService.isInitialized()) {
            // Display a message when no workspace is open or DB is not initialized
            const item = new vscode.TreeItem('Open a folder to see snapshots', vscode.TreeItemCollapsibleState.None);
            return [item as any as SnapshotTreeItem];
        }

        try {
            const snapshots = await dbService.getSnapshots();
            if (snapshots.length === 0) {
                const item = new vscode.TreeItem('No snapshots saved for this workspace', vscode.TreeItemCollapsibleState.None);
                return [item as any as SnapshotTreeItem];
            }
            return snapshots.map(snapshot => new SnapshotTreeItem(
                snapshot,
                vscode.TreeItemCollapsibleState.None
            ));
        } catch (error) {
            console.error('Error fetching snapshots:', error);
            const item = new vscode.TreeItem('Error loading snapshots', vscode.TreeItemCollapsibleState.None);
            return [item as any as SnapshotTreeItem];
        }
    }
}

// ... (SnapshotTreeItem class remains the same)
class SnapshotTreeItem extends vscode.TreeItem {
    constructor(
        public readonly snapshot: ISnapshot,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState
    ) {
        super(snapshot.name, collapsibleState);
        this.tooltip = `${snapshot.notebook_path}\n${new Date(parseInt(snapshot.created_at) * 1000).toLocaleString()}`;
        this.description = new Date(parseInt(snapshot.created_at) * 1000).toLocaleDateString();
        this.command = {
            command: 'mcp-jupyter.viewSnapshot',
            title: 'View Snapshot',
            arguments: [snapshot]
        };
    }
}

