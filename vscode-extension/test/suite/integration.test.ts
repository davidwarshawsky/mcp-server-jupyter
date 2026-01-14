import * as assert from 'assert';
import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as crypto from 'crypto';
import { spawnTestServer, cleanupTestServer } from './testHelper';

/**
 * Integration Test: VSCode + MCP Server + Jupyter Kernel
 * 
 * This test actually spawns the Python server and ensures it can
 * execute code in a real notebook. It is NOT a mock.
 */
suite('Integration Test Suite', function() {
    this.timeout(60000); // 60s timeout for real kernel startup

    const tempDir = path.join(process.cwd(), 'temp_test_workspace');
    const notebookPath = path.join(tempDir, 'integration_test.ipynb');
    let serverProc: any = null;

    suiteSetup(async () => {
        // 1. Create temp workspace
        if (!fs.existsSync(tempDir)) {
            fs.mkdirSync(tempDir);
        }

        // 2. Spawn the test server and configure extension
        const { proc, port } = await spawnTestServer();
        serverProc = proc;
        console.log(`[Integration Test] Server running on port ${port}`);

        // 3. Create a dummy notebook
        const initialNotebookContent = {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": null,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "print('HELLO FROM INTEGRATION TEST')"
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
        // Cleanup
        cleanupTestServer(serverProc);
        if (fs.existsSync(notebookPath)) {
            try { fs.unlinkSync(notebookPath); } catch {}
        }
        if (fs.existsSync(tempDir)) {
            try { fs.rmdirSync(tempDir); } catch {}
        }
    });

    test('Should execute cell via MCP Server', async () => {
        // 1. Open Notebook
        const uri = vscode.Uri.file(notebookPath);
        const doc = await vscode.workspace.openNotebookDocument(uri);
        await vscode.window.showNotebookDocument(doc);
        
        assert.strictEqual(doc.cellCount, 1);

        // 2. Wait for Kernel to be Ready (Implicitly handled by extension, but we might need to wait)
        // In a real user scenario, they select a controller.
        // For automation, we might need to rely on the extension's auto-selection or command.
        
        // However, since we can't easily GUI test the controller selection in this harness,
        // we will invoke the MCP Client directly if exposed, OR check if the changes we triggered happened.

        // Simulating the "Run Cell" action via Command Palette might be flaky without setting up the controller.
        // Instead, let's verify the Extension <-> Server connection is live by checking the logs channel or configuration.
        
        const config = vscode.workspace.getConfiguration('mcp-jupyter');
        const configuredPath = config.get('pythonPath');
        assert.ok(configuredPath, 'Python Path should be configured');

        // 3. Execute via MCP client directly (reliable in headless harness)
        // GUI-driven execution via VS Code's notebook controller selection can be flaky in CI.
        const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
        assert.ok(extension, 'Extension not found');
        const extensionApi = await extension.activate() as any;
        const client = extensionApi.mcpClient;
        assert.ok(client, 'MCP Client should be accessible via Extension API');
        assert.strictEqual(client.getStatus(), 'running', 'MCP Server should be running');

        // Ensure a kernel is started for this notebook
        await client.startKernel(notebookPath);

        // Run the code and stream outputs until completion
        const taskId = crypto.randomUUID();
        await client.runCellAsync(notebookPath, 0, "print('HELLO FROM INTEGRATION TEST')", taskId);

        let stdout = '';
        let nextIndex = 0;
        const started = Date.now();
        const maxMs = 30000;
        while (Date.now() - started < maxMs) {
            const stream = await client.getExecutionStream(notebookPath, taskId, nextIndex);
            nextIndex = stream.next_index ?? nextIndex;

            if (Array.isArray(stream.new_outputs)) {
                for (const o of stream.new_outputs) {
                    if (o?.output_type === 'stream' && (o as any).name === 'stdout') {
                        stdout += (o as any).text ?? '';
                    }
                }
            }

            if (stream.status === 'completed') {
                break;
            }
            await new Promise(resolve => setTimeout(resolve, 250));
        }

        assert.ok(stdout.includes('HELLO FROM INTEGRATION TEST'), `Expected stdout to include greeting, got: ${stdout}`);
        
        assert.strictEqual(doc.notebookType, 'jupyter-notebook');
    });
});
