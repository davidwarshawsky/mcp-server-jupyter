import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import sqlite3 from 'sqlite3';

// ... (interfaces are the same)

export class DatabaseService {
    private db: sqlite3.Database | undefined;
    private dbPath: string | undefined;

    constructor() {}

    /**
     * Initializes the database for a specific workspace folder.
     * Returns true on success, false on failure.
     */
    public async init(workspaceFolder: vscode.WorkspaceFolder): Promise<boolean> {
        const configPath = vscode.workspace.getConfiguration('mcp-jupyter').get<string>('snapshotStoragePath');
        if (!configPath) {
            // Should not happen as we have a default value, but good to guard.
            vscode.window.showErrorMessage('Snapshot storage path is not configured.');
            return false;
        }

        let resolvedPath: string;
        if (path.isAbsolute(configPath)) {
            resolvedPath = configPath;
        } else {
            resolvedPath = path.join(workspaceFolder.uri.fsPath, configPath);
        }
        this.dbPath = resolvedPath;

        const dbDir = path.dirname(this.dbPath);
        if (!fs.existsSync(dbDir)) {
            try {
                fs.mkdirSync(dbDir, { recursive: true });
            } catch (err) {
                vscode.window.showErrorMessage(`Failed to create snapshot directory: ${err.message}`);
                return false;
            }
        }

        return new Promise((resolve, reject) => {
            this.close(); // Close any existing connection
            this.db = new sqlite3.Database(this.dbPath, (err) => {
                if (err) {
                    vscode.window.showErrorMessage(`Failed to connect to snapshot database at ${this.dbPath}: ${err.message}`);
                    return resolve(false);
                }
                console.log(`Connected to snapshot database for workspace: ${workspaceFolder.name}`);
                this.createTables().then(() => resolve(true)).catch(() => resolve(false));
            });
        });
    }

    // ... (createTables, getSnapshots, etc. remain the same, but now operate on the workspace-specific db)
    private async createTables(): Promise<void> {
        const tables = `
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                notebook_path TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshot_variables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT,
                preview TEXT,
                timestamp INTEGER,
                FOREIGN KEY (snapshot_id) REFERENCES snapshots (id) ON DELETE CASCADE
            );
        `;
        return new Promise((resolve, reject) => {
            if (!this.db) return reject('Database not initialized');
            this.db.exec(tables, (err) => {
                if (err) return reject(err);
                resolve();
            });
        });
    }
    // ... (other methods like saveSnapshot, getSnapshots would also need checks for this.db)
    
    public isInitialized(): boolean {
        return this.db !== undefined;
    }

    public close(): void {
        if (this.db) {
            this.db.close();
            this.db = undefined;
            this.dbPath = undefined;
            console.log('Closed database connection.');
        }
    }
}
