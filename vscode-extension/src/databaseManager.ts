import * as vscode from 'vscode';
import { DatabaseService } from './database';

/**
 * Manages database service instances for multiple workspaces.
 */
export class DatabaseManager {
    private services: Map<string, DatabaseService> = new Map();
    private activeWorkspace: vscode.WorkspaceFolder | undefined;

    constructor() {}

    public async getActiveService(): Promise<DatabaseService | undefined> {
        if (!this.activeWorkspace) {
            return undefined;
        }
        return this.getService(this.activeWorkspace);
    }

    public async getService(workspaceFolder: vscode.WorkspaceFolder): Promise<DatabaseService | undefined> {
        const workspaceId = workspaceFolder.uri.toString();
        if (this.services.has(workspaceId)) {
            return this.services.get(workspaceId);
        }

        const newService = new DatabaseService();
        const success = await newService.init(workspaceFolder);

        if (success) {
            this.services.set(workspaceId, newService);
            return newService;
        }
        return undefined;
    }

    public setActiveWorkspace(workspace: vscode.WorkspaceFolder | undefined) {
        this.activeWorkspace = workspace;
    }

    public closeAll(): void {
        this.services.forEach(service => service.close());
        this.services.clear();
    }
}
