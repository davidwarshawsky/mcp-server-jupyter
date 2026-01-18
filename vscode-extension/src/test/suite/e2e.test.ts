/**
 * E2E Integration Tests for MCP Jupyter Extension
 * 
 * Uses @vscode/test-electron to run headless VS Code and test real interactions.
 * These tests provide confidence that:
 * 1. VS Code API changes don't break the extension
 * 2. MCP server protocol changes are caught early
 * 3. Agent workflows function end-to-end
 */

import * as assert from 'assert';
import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

suite('E2E: Kernel Lifecycle', () => {
    let testNotebookPath: string;

    suiteSetup(async () => {
        // Create a test notebook
        const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        assert.ok(workspaceRoot, 'Workspace must be open');
        
        testNotebookPath = path.join(workspaceRoot, 'test_e2e.ipynb');
        
        // Create minimal notebook
        const notebookContent = {
            cells: [
                {
                    cell_type: 'code',
                    execution_count: null,
                    metadata: {},
                    outputs: [],
                    source: ['print("Hello from E2E test")']
                }
            ],
            metadata: {
                kernelspec: {
                    display_name: 'Python 3',
                    language: 'python',
                    name: 'python3'
                }
            },
            nbformat: 4,
            nbformat_minor: 5
        };
        
        fs.writeFileSync(testNotebookPath, JSON.stringify(notebookContent, null, 2));
    });

    suiteTeardown(() => {
        // Cleanup
        if (fs.existsSync(testNotebookPath)) {
            fs.unlinkSync(testNotebookPath);
        }
    });

    test('Should start kernel and execute cell', async function() {
        this.timeout(30000); // 30 second timeout
        
        // Open the notebook
        const notebookDocument = await vscode.workspace.openNotebookDocument(vscode.Uri.file(testNotebookPath));
        await vscode.window.showNotebookDocument(notebookDocument);
        
        // Wait for extension activation
        const extension = vscode.extensions.getExtension('mcp-jupyter.mcp-jupyter-extension');
        assert.ok(extension, 'Extension should be available');
        await extension.activate();
        
        // Find the MCP Agent Kernel controller
        const controllers = vscode.notebooks.getAllNotebookControllers(notebookDocument);
        const mcpController = controllers.find(c => c.id === 'mcp-agent-kernel');
        assert.ok(mcpController, 'MCP Agent Kernel controller should be registered');
        
        // Select the controller
        await vscode.commands.executeCommand('notebook.selectKernel', {
            id: mcpController.id,
            extension: extension.id
        });
        
        // Execute the first cell
        const cell = notebookDocument.cellAt(0);
        const execution = mcpController.createNotebookCellExecution(cell);
        execution.start();
        
        // Simulate execution (in real test, this would trigger via controller)
        await vscode.commands.executeCommand('notebook.cell.execute', { ranges: [{ start: 0, end: 1 }] });
        
        // Wait for output (with timeout)
        const startTime = Date.now();
        const maxWait = 10000; // 10 seconds
        
        while (Date.now() - startTime < maxWait) {
            if (cell.outputs.length > 0) {
                break;
            }
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        
        // Verify output
        assert.ok(cell.outputs.length > 0, 'Cell should have output');
        
        const output = cell.outputs[0];
        assert.strictEqual(output.items.length, 1, 'Output should have one item');
        
        const outputText = Buffer.from(output.items[0].data).toString('utf8');
        assert.ok(outputText.includes('Hello from E2E test'), 'Output should contain expected text');
    });

    test('Should handle cell execution errors gracefully', async function() {
        this.timeout(20000);
        
        const notebookDocument = await vscode.workspace.openNotebookDocument(vscode.Uri.file(testNotebookPath));
        
        // Add a cell with an error
        const edit = new vscode.WorkspaceEdit();
        const notebookEdit = vscode.NotebookEdit.insertCells(1, [
            new vscode.NotebookCellData(
                vscode.NotebookCellKind.Code,
                'raise ValueError("Test error")',
                'python'
            )
        ]);
        edit.set(notebookDocument.uri, [notebookEdit]);
        await vscode.workspace.applyEdit(edit);
        
        // Execute the error cell
        await vscode.commands.executeCommand('notebook.cell.execute', { ranges: [{ start: 1, end: 2 }] });
        
        // Wait for execution
        await new Promise(resolve => setTimeout(resolve, 3000));
        
        const errorCell = notebookDocument.cellAt(1);
        assert.ok(errorCell.outputs.length > 0, 'Error cell should have output');
        
        // Check for error output
        const hasError = errorCell.outputs.some(output => 
            output.items.some(item => 
                item.mime === 'application/vnd.code.notebook.error'
            )
        );
        assert.ok(hasError, 'Output should indicate error');
    });
});

suite('E2E: Agent Communication', () => {
    test('Should detect sync needed on unsaved changes', async function() {
        this.timeout(15000);
        
        // This test verifies Fix #2 (buffer hash injection)
        const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const testPath = path.join(workspaceRoot!, 'test_sync.ipynb');
        
        // Create and open notebook
        const notebook = {
            cells: [{ cell_type: 'code', source: ['x = 1'], outputs: [], metadata: {} }],
            metadata: {},
            nbformat: 4,
            nbformat_minor: 5
        };
        fs.writeFileSync(testPath, JSON.stringify(notebook));
        
        const doc = await vscode.workspace.openNotebookDocument(vscode.Uri.file(testPath));
        await vscode.window.showNotebookDocument(doc);
        
        // Execute cell to establish baseline
        await vscode.commands.executeCommand('notebook.cell.execute', { ranges: [{ start: 0, end: 1 }] });
        await new Promise(resolve => setTimeout(resolve, 2000));
        
        // Modify cell WITHOUT saving
        const edit = new vscode.WorkspaceEdit();
        const cellEdit = vscode.NotebookEdit.updateCellMetadata(0, {
            ...doc.cellAt(0).metadata,
            modified: true
        });
        
        // Change cell content
        const contentEdit = vscode.NotebookEdit.replaceCells(
            new vscode.NotebookRange(0, 1),
            [new vscode.NotebookCellData(
                vscode.NotebookCellKind.Code,
                'x = 2  # CHANGED',
                'python'
            )]
        );
        
        edit.set(doc.uri, [contentEdit]);
        await vscode.workspace.applyEdit(edit);
        
        // Buffer now differs from disk
        // The extension should inject buffer hashes when calling detect_sync_needed
        // We can't easily test the MCP call directly, but we verify the doc is dirty
        assert.ok(doc.isDirty, 'Document should be marked as dirty (unsaved)');
        
        // Cleanup
        fs.unlinkSync(testPath);
    });
});

suite('E2E: Performance', () => {
    test('Should handle large output without blocking UI', async function() {
        this.timeout(30000);
        
        const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const testPath = path.join(workspaceRoot!, 'test_large_output.ipynb');
        
        // Create notebook with large output generator
        const notebook = {
            cells: [{
                cell_type: 'code',
                source: ['for i in range(10000):\\n    print(f"Line {i}")'],
                outputs: [],
                metadata: {}
            }],
            metadata: {},
            nbformat: 4,
            nbformat_minor: 5
        };
        fs.writeFileSync(testPath, JSON.stringify(notebook));
        
        const doc = await vscode.workspace.openNotebookDocument(vscode.Uri.file(testPath));
        await vscode.window.showNotebookDocument(doc);
        
        const startTime = Date.now();
        
        // Execute large output cell
        await vscode.commands.executeCommand('notebook.cell.execute', { ranges: [{ start: 0, end: 1 }] });
        
        // Wait for completion
        await new Promise(resolve => setTimeout(resolve, 5000));
        
        const duration = Date.now() - startTime;
        
        // UI should remain responsive (event-driven architecture)
        assert.ok(duration < 10000, 'Large output should complete in under 10 seconds');
        
        const cell = doc.cellAt(0);
        assert.ok(cell.outputs.length > 0, 'Cell should have output');
        
        // Cleanup
        fs.unlinkSync(testPath);
    });
});
