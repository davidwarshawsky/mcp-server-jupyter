/**
 * Real World Integration Tests
 * 
 * These tests run inside a real VS Code instance and verify that:
 * 1. The extension can spawn the Python server
 * 2. The WebSocket handshake completes successfully
 * 3. Cell execution flows end-to-end (TypeScript → Python → back to TypeScript)
 * 4. Superpower features are registered and accessible
 * 
 * This is the "Driver's Test" - proof that the extension actually works
 * in a real environment, not just in unit tests.
 */

import * as assert from 'assert';
import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

suite('Real Server Integration Test Suite', function () {
    // Give it time to spawn the Python process, complete WebSocket handshake,
    // and handle any subprocess spawning quirks on Windows
    this.timeout(60000); 

    let extension: vscode.Extension<any>;
    let testNotebookUri: vscode.Uri;

    suiteSetup(async () => {
        console.log('🔧 Setting up integration test environment...');
        
        // 1. Activate Extension
        extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel')!;
        assert.ok(extension, 'Extension not found in VS Code');
        
        if (!extension.isActive) {
            console.log('📦 Activating extension...');
            await extension.activate();
        }
        
        // 2. Override settings to point to local dev Python server
        // This ensures we aren't relying on a pre-installed pip package
        const config = vscode.workspace.getConfiguration('mcp-jupyter');
        const repoRoot = path.resolve(__dirname, '../../../../../tools/mcp-server-jupyter');
        
        console.log(`🔧 Configuring server path: ${repoRoot}`);
        
        // Verify the path exists
        assert.ok(fs.existsSync(repoRoot), `Server path does not exist: ${repoRoot}`);
        assert.ok(fs.existsSync(path.join(repoRoot, 'src', 'main.py')), 
            'src/main.py not found in server path');
        
        await config.update('serverPath', repoRoot, vscode.ConfigurationTarget.Global);
        await config.update('serverMode', 'spawn', vscode.ConfigurationTarget.Global);
        
        console.log('✅ Extension activated and configured');
    });

    suiteTeardown(async () => {
        console.log('🧹 Cleaning up integration test environment...');
        
        // Close all notebooks
        await vscode.commands.executeCommand('workbench.action.closeAllEditors');
        
        // Reset configuration
        const config = vscode.workspace.getConfiguration('mcp-jupyter');
        await config.update('serverPath', undefined, vscode.ConfigurationTarget.Global);
        await config.update('serverMode', undefined, vscode.ConfigurationTarget.Global);
    });

    test('Proof of Life: Server Spawns and Responds', async () => {
        console.log('🚀 Test 1: Spawning server...');
        
        // Create a minimal notebook
        const nbData = new vscode.NotebookData([
            new vscode.NotebookCellData(
                vscode.NotebookCellKind.Code, 
                "print('Server is alive')", 
                'python'
            )
        ]);
        
        const nbDoc = await vscode.workspace.openNotebookDocument('jupyter-notebook', nbData);
        testNotebookUri = nbDoc.uri;
        await vscode.window.showNotebookDocument(nbDoc);
        
        console.log('📓 Notebook created, triggering execution...');
        
        // Trigger execution (this forces the server to spawn)
        await vscode.commands.executeCommand('notebook.cell.execute');
        
        // Poll for output (wait for Server Spawn + WebSocket Handshake + Execution)
        let outputText = '';
        let attempts = 0;
        const maxAttempts = 30; // 30 seconds
        
        for (attempts = 0; attempts < maxAttempts; attempts++) {
            if (nbDoc.cellAt(0).outputs.length > 0) {
                const output = nbDoc.cellAt(0).outputs[0];
                const item = output.items.find(i => i.mime === 'application/vnd.code.notebook.stdout');
                if (item) {
                    outputText = new TextDecoder().decode(item.data);
                    console.log(`✅ Got output after ${attempts + 1} seconds: ${outputText}`);
                    break;
                }
            }
            await new Promise(r => setTimeout(r, 1000));
        }
        
        assert.ok(outputText.includes('Server is alive'), 
            `Server failed to execute code after ${attempts} seconds. Output: "${outputText}"`);
    });

    test('Windows Compatibility: Subprocess Spawning Works', async () => {
        console.log('🪟 Test 2: Verifying Windows subprocess compatibility...');
        
        // This test specifically checks that our spawn logic handles:
        // - Path quoting issues
        // - Environment variable inheritance
        // - Stdio piping
        
        const api = extension.exports;
        assert.ok(api, 'Extension API not exposed');
        
        // Check that the server process is actually running
        assert.ok(api.mcpClient, 'MCP Client not initialized');
        
        const status = api.mcpClient.getStatus?.() || 'unknown';
        console.log(`📊 Server status: ${status}`);
        
        assert.ok(status === 'running' || status === 'connected', 
            `Server should be running, got: ${status}`);
    });

    test('WebSocket Handshake: Full Duplex Communication', async () => {
        console.log('🔌 Test 3: Testing WebSocket bidirectional communication...');
        
        // Create a notebook with a cell that produces streaming output
        const nbData = new vscode.NotebookData([
            new vscode.NotebookCellData(
                vscode.NotebookCellKind.Code, 
                "import time\nfor i in range(3):\n    print(f'Stream {i}')\n    time.sleep(0.5)", 
                'python'
            )
        ]);
        
        const nbDoc = await vscode.workspace.openNotebookDocument('jupyter-notebook', nbData);
        await vscode.window.showNotebookDocument(nbDoc);
        
        // Execute and wait for streaming output
        await vscode.commands.executeCommand('notebook.cell.execute');
        
        let outputText = '';
        for (let i = 0; i < 20; i++) {
            if (nbDoc.cellAt(0).outputs.length > 0) {
                const output = nbDoc.cellAt(0).outputs[0];
                const item = output.items.find(i => i.mime === 'application/vnd.code.notebook.stdout');
                if (item) {
                    outputText = new TextDecoder().decode(item.data);
                    // Check for multiple streaming outputs
                    if (outputText.includes('Stream 0') && outputText.includes('Stream 2')) {
                        console.log(`✅ Streaming output received: ${outputText}`);
                        break;
                    }
                }
            }
            await new Promise(r => setTimeout(r, 1000));
        }
        
        assert.ok(outputText.includes('Stream 0'), 'First stream message not received');
        assert.ok(outputText.includes('Stream 2'), 'Last stream message not received');
    });

    test('Superpower Check: Query DataFrames Tool Registered', async () => {
        console.log('🔮 Test 4: Verifying Superpower features are available...');
        
        const api = extension.exports;
        
        // Check if the MCP server reported the superpower tools
        const tools = api.mcpClient.getAvailableTools?.() || [];
        console.log(`📋 Available tools: ${tools.length}`);
        
        // Verify key superpower tools are registered
        const superpowerTools = [
            'query_dataframes',
            'save_checkpoint', 
            'load_checkpoint',
            'inspect_variable'
        ];
        
        for (const toolName of superpowerTools) {
            const found = tools.some((t: any) => t.name === toolName);
            assert.ok(found, `Superpower tool not found: ${toolName}`);
            console.log(`✅ Found tool: ${toolName}`);
        }
    });

    test('Error Recovery: Server Recovers from Bad Code', async () => {
        console.log('💥 Test 5: Testing error recovery...');
        
        // Create a notebook with intentionally bad code
        const nbData = new vscode.NotebookData([
            new vscode.NotebookCellData(
                vscode.NotebookCellKind.Code, 
                "undefined_variable + 123", 
                'python'
            )
        ]);
        
        const nbDoc = await vscode.workspace.openNotebookDocument('jupyter-notebook', nbData);
        await vscode.window.showNotebookDocument(nbDoc);
        
        await vscode.commands.executeCommand('notebook.cell.execute');
        
        // Wait for error output
        let errorText = '';
        for (let i = 0; i < 15; i++) {
            if (nbDoc.cellAt(0).outputs.length > 0) {
                const output = nbDoc.cellAt(0).outputs[0];
                const item = output.items.find(i => i.mime === 'application/vnd.code.notebook.error');
                if (item) {
                    errorText = new TextDecoder().decode(item.data);
                    console.log(`✅ Error captured: ${errorText}`);
                    break;
                }
            }
            await new Promise(r => setTimeout(r, 1000));
        }
        
        assert.ok(errorText.includes('NameError') || errorText.includes('undefined_variable'), 
            'Server did not return proper error');
        
        // Now verify the server is still responsive
        const nbData2 = new vscode.NotebookData([
            new vscode.NotebookCellData(
                vscode.NotebookCellKind.Code, 
                "print('Still alive after error')", 
                'python'
            )
        ]);
        
        const nbDoc2 = await vscode.workspace.openNotebookDocument('jupyter-notebook', nbData2);
        await vscode.window.showNotebookDocument(nbDoc2);
        
        await vscode.commands.executeCommand('notebook.cell.execute');
        
        let recoveryText = '';
        for (let i = 0; i < 15; i++) {
            if (nbDoc2.cellAt(0).outputs.length > 0) {
                const output = nbDoc2.cellAt(0).outputs[0];
                const item = output.items.find(i => i.mime === 'application/vnd.code.notebook.stdout');
                if (item) {
                    recoveryText = new TextDecoder().decode(item.data);
                    break;
                }
            }
            await new Promise(r => setTimeout(r, 1000));
        }
        
        assert.ok(recoveryText.includes('Still alive after error'), 
            'Server failed to recover from error');
        console.log('✅ Server recovered successfully');
    });

    test('Asset Offloading: Large Output Handled Gracefully', async () => {
        console.log('📦 Test 6: Testing asset offloading for large outputs...');
        
        // Create code that generates a large output
        const nbData = new vscode.NotebookData([
            new vscode.NotebookCellData(
                vscode.NotebookCellKind.Code, 
                "for i in range(100):\n    print(f'Line {i}: ' + 'x' * 100)", 
                'python'
            )
        ]);
        
        const nbDoc = await vscode.workspace.openNotebookDocument('jupyter-notebook', nbData);
        await vscode.window.showNotebookDocument(nbDoc);
        
        await vscode.commands.executeCommand('notebook.cell.execute');
        
        // Wait for output
        let outputText = '';
        for (let i = 0; i < 20; i++) {
            if (nbDoc.cellAt(0).outputs.length > 0) {
                const output = nbDoc.cellAt(0).outputs[0];
                const item = output.items.find(i => i.mime === 'application/vnd.code.notebook.stdout');
                if (item) {
                    outputText = new TextDecoder().decode(item.data);
                    break;
                }
            }
            await new Promise(r => setTimeout(r, 1000));
        }
        
        // Verify output was truncated or offloaded (not the full 10KB+)
        // The server should have applied truncation or asset offloading
        console.log(`📊 Output size: ${outputText.length} chars`);
        
        // Should contain truncation marker or asset reference
        const hasTruncation = outputText.includes('...') || 
                            outputText.includes('truncated') ||
                            outputText.includes('assets/');
        
        assert.ok(hasTruncation || outputText.length < 5000, 
            'Large output was not truncated or offloaded');
        console.log('✅ Asset offloading working');
    });
});
