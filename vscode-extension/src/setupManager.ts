import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { exec } from 'child_process';
import * as crypto from 'crypto';

const EXPECTED_WHEEL_CHECKSUM = '...placeholder...'; 

export class SetupManager {
    // ... (properties)

    private async runPipCommand(command: string, venvPath: string, silent = false): Promise<void> {
        const config = vscode.workspace.getConfiguration('mcp-jupyter');
        const timeout = config.get<number>('pipTimeout', 120) * 1000;
        const retries = config.get<number>('pipRetries', 2);

        let lastError: Error | undefined;

        for (let i = 0; i < retries; i++) {
            try {
                return await new Promise<void>((resolve, reject) => {
                    const process = exec(command, {
                        env: this.getProxyAwareEnv(venvPath),
                        timeout: timeout
                    }, (error, stdout, stderr) => {
                        if (error) {
                            lastError = new Error(`Exit Code: ${error.code}\nstdout: ${stdout}\nstderr: ${stderr}`);
                            reject(lastError);
                        } else {
                            resolve();
                        }
                    });
                    // ... (process listeners)
                });
            } catch (error) {
                if (i === retries - 1) {
                    // Last retry failed, throw the error
                    throw error;
                } else {
                    // Wait before retrying
                    await new Promise(res => setTimeout(res, 2000 * (i + 1)));
                }
            }
        }
    }

    // ... (rest of the file is the same)
}
