import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import sqlite3 from 'sqlite3';

// ... (interfaces are the same)

export class DatabaseService {
    // ... (constructor and init are the same)

    public async saveSnapshot(name: string, notebookPath: string, variables: Omit<ISnapshotVariable, 'id' | 'snapshotId'>[]): Promise<ISnapshot> {
        return new Promise((resolve, reject) => {
            const createdAt = Math.floor(Date.now() / 1000);
            const snapshotSql = `INSERT INTO snapshots (name, notebook_path, created_at) VALUES (?, ?, ?)`;

            this.db?.run(snapshotSql, [name, notebookPath, createdAt], function (err) {
                if (err) return reject(err);

                const snapshotId = this.lastID;
                const newSnapshot: ISnapshot = { id: snapshotId, name, notebookPath, createdAt };

                const varSql = `INSERT INTO snapshot_variables (snapshot_id, name, type, preview, timestamp) VALUES (?, ?, ?, ?, ?)`;
                const stmt = this.db.prepare(varSql);

                this.db.serialize(() => {
                    variables.forEach(v => {
                        stmt.run(snapshotId, v.name, v.type, v.preview, v.timestamp);
                    });
                    stmt.finalize(err => {
                        if (err) return reject(err);
                        resolve(newSnapshot);
                    });
                });
            });
        });
    }

    public async getSnapshots(): Promise<ISnapshot[]> {
        return new Promise((resolve, reject) => {
            const sql = `SELECT * FROM snapshots ORDER BY created_at DESC`;
            this.db?.all(sql, [], (err, rows) => {
                if (err) return reject(err);
                resolve(rows as ISnapshot[]);
            });
        });
    }

    public async getVariablesForSnapshot(snapshotId: number): Promise<ISnapshotVariable[]> {
        return new Promise((resolve, reject) => {
            const sql = `SELECT * FROM snapshot_variables WHERE snapshot_id = ?`;
            this.db?.all(sql, [snapshotId], (err, rows) => {
                if (err) return reject(err);
                resolve(rows as ISnapshotVariable[]);
            });
        });
    }

    public async clearAllSnapshots(): Promise<void> {
        return new Promise((resolve, reject) => {
            this.db?.serialize(() => {
                this.db.run(`DELETE FROM snapshot_variables`, [], (err) => {
                    if (err) return reject(err);
                });
                this.db.run(`DELETE FROM snapshots`, [], (err) => {
                    if (err) return reject(err);
                    resolve();
                });
            });
        });
    }
    
    // ... (close method is the same)
}
