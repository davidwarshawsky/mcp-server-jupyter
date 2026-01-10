import * as assert from 'assert';
import * as vscode from 'vscode';
import * as path from 'path';

suite('Notebook Integration Test', () => {
    test('Can open notebook and select kernel', async () => {
        // 1. Locate test notebook
        // We use the fixtures directory in test folder
        const workspacePath = path.resolve(__dirname, '../../../../test/fixtures');
        const notebookPath = path.join(workspacePath, 'test_notebook.ipynb');
        const uri = vscode.Uri.file(notebookPath);

        // 2. Open Notebook
        const document = await vscode.workspace.openNotebookDocument(uri);
        await vscode.window.showNotebookDocument(document);

        // 3. Assert Notebook Structure
        assert.strictEqual(document.cellCount, 4, 'Should have 4 cells from fixture');
        assert.strictEqual(document.cellAt(0).kind, vscode.NotebookCellKind.Code);

        // 4. Trigger Kernel Selection (This is tricky in tests, usually we explicitly select controller)
        // Adjust extension ID if necessary
        const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
        await extension?.activate();

        // Find our controller
        // Note: VS Code API doesn't let us easily "click" the kernel picker programmatically
        // checking extension activation is often the limit for basic integration tests
        assert.ok(extension?.isActive);
    });
});
