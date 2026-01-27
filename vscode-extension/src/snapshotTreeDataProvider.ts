import * as vscode from 'vscode';
import { DatabaseService, ISnapshot } from './database';

export class SnapshotTreeDataProvider implements vscode.TreeDataProvider<SnapshotTreeItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<SnapshotTreeItem | undefined | null | void> = new vscode.EventEmitter<SnapshotTreeItem | undefined | null | void>();
    readonly onDidChangeTreeData: vscode.Event<SnapshotTreeItem | undefined | null | void> = this._onDidChangeTreeData.event;

    constructor(private databaseService: DatabaseService) {}

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element: SnapshotTreeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: SnapshotTreeItem): Promise<SnapshotTreeItem[]> {
        if (element) {
            // We have no nested items, so return empty array
            return [];
        }

        const snapshots = await this.databaseService.getSnapshots();
        return snapshots.map(snapshot => new SnapshotTreeItem(
            snapshot,
            vscode.TreeItemCollapsibleState.None
        ));
    }
}

class SnapshotTreeItem extends vscode.TreeItem {
    constructor(
        public readonly snapshot: ISnapshot,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState
    ) {
        super(snapshot.name, collapsibleState);
        this.tooltip = `${snapshot.notebookPath}\n${new Date(snapshot.createdAt * 1000).toLocaleString()}`;
        this.description = new Date(snapshot.createdAt * 1000).toLocaleDateString();
        this.command = {
            command: 'mcp-jupyter.viewSnapshot',
            title: 'View Snapshot',
            arguments: [snapshot]
        };
    }
}
