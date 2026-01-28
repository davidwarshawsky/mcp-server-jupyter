import * as vscode from 'vscode';

export interface ISnapshot {
    id: number;
    name: string;
    notebook_path: string;
    created_at: string;
}

export interface ISnapshotVariable {
    id: number;
    snapshot_id: number;
    var_name: string;
    var_type: string;
    var_value: string;
}

export class DatabaseService {
    private db: any | undefined;
    private dbPath: string | undefined;

    constructor() {}

    public async init(workspaceFolder: vscode.WorkspaceFolder): Promise<boolean> {
        console.warn('Snapshot feature is not available in this build.');
        return false;
    }

    public async saveSnapshot(name: string, notebookPath: string, variables: any[]): Promise<void> {
        throw new Error('Snapshot feature not available');
    }

    public async getSnapshots(): Promise<ISnapshot[]> {
        return [];
    }

    public async getVariablesForSnapshot(snapshotId: number): Promise<ISnapshotVariable[]> {
        return [];
    }

    public async clearAllSnapshots(): Promise<void> {
        // No-op
    }

    public close(): void {
        // No-op
    }

    public isInitialized(): boolean {
        return false;
    }
}
