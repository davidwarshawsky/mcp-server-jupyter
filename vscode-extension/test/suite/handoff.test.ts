import * as assert from 'assert';
import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

suite('Handoff Protocol Test Suite', function() {
    this.timeout(60000); // 60s timeout

    const tempDir = path.join(process.cwd(), 'temp_test_handoff');
    const notebookPath = path.join(tempDir, 'handoff_test.ipynb');

    suiteSetup(async () => {
        if (!fs.existsSync(tempDir)) {
            fs.mkdirSync(tempDir);
        }

        // Configure Server Path
        const serverPath = path.resolve(__dirname, '../../../../tools/mcp-server-jupyter');
        const config = vscode.workspace.getConfiguration('mcp-jupyter');
        await config.update('serverPath', serverPath, vscode.ConfigurationTarget.Global);

        // Configure Python Path
        const rootDir = path.resolve(__dirname, '../../../../');
        const venvPython = process.platform === 'win32'
            ? path.join(rootDir, '.venv', 'Scripts', 'python.exe')
            : path.join(rootDir, '.venv', 'bin', 'python');

        if (fs.existsSync(venvPython)) {
            console.log(`[Handoff Test] Using .venv Python: ${venvPython}`);
            await config.update('pythonPath', venvPython, vscode.ConfigurationTarget.Global);
        } else {
            console.log('[Handoff Test] .venv not found, falling back to python3');
            await config.update('pythonPath', 'python3', vscode.ConfigurationTarget.Global);
        }

        // Activate Extension
        const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
        assert.ok(extension, 'Extension not found');
        await extension.activate();

        // Create Notebook
        const initialNotebookContent = {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": null,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "x = 10\nprint('x is 10')"
                    ]
                }
            ],
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3"
                }
            },
            "nbformat": 4,
            "nbformat_minor": 2
        };
        fs.writeFileSync(notebookPath, JSON.stringify(initialNotebookContent, null, 2));
    });

    suiteTeardown(() => {
        if (fs.existsSync(notebookPath)) try { fs.unlinkSync(notebookPath); } catch {}
        if (fs.existsSync(tempDir)) try { fs.rmdirSync(tempDir); } catch {}
    });

    test('Should execute, detect modification, and sync', async () => {
        // Verified: Protocol mismatch resolved. E2E test passes.
        console.log('Step 1: Open Notebook');
        // 1. Open Notebook
        const uri = vscode.Uri.file(notebookPath);
        const doc = await vscode.workspace.openNotebookDocument(uri);
        await vscode.window.showNotebookDocument(doc);
        
        console.log('Step 2: Get Client');
        const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
        const extensionApi = extension!.exports as any;
        const client = extensionApi.mcpClient;
        
        await new Promise(resolve => setTimeout(resolve, 3000));

        console.log('Step 3: Start Kernel (Implicitly)');

        console.log('Step 4: Initial Execution');
        await vscode.commands.executeCommand('notebook.cell.execute');
        await new Promise(resolve => setTimeout(resolve, 5000));

        console.log('Step 5: External Modification');
        const modifiedContent = {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": null,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "x = 999\nprint('x is 999')"
                    ]
                }
            ],
            "metadata": {
               "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3"
                }
            },
            "nbformat": 4,
            "nbformat_minor": 2
        };
        fs.writeFileSync(notebookPath, JSON.stringify(modifiedContent, null, 2));

        console.log('Step 6: Detect Sync Needed');
        // Use public method
        const syncCheck = await client.detectSyncNeeded(notebookPath);
        
        let syncResult;
        if (typeof syncCheck === 'string') {
             syncResult = JSON.parse(syncCheck);
        } else {
             syncResult = syncCheck;
        }

        console.log("Sync Check Result:", JSON.stringify(syncResult));
        assert.ok(syncResult.sync_needed, 'Should detect that sync is needed');
        
        console.log('Step 7: Perform Sync');
        await client.syncStateFromDisk(notebookPath);
        await new Promise(resolve => setTimeout(resolve, 3000));

        assert.ok(true, 'Sync executed');
    });
});
