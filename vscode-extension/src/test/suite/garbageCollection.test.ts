import * as assert from 'assert';
import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';

suite('Garbage Collection Integration Test', function () {
  this.timeout(60000); // 60s timeout

  let tempDir: string;
  let notebookPath: string;
  let assetsDir: string;

  suiteSetup(async () => {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-jupyter-gc-'));
    notebookPath = path.join(tempDir, 'gc_test.ipynb');
    assetsDir = path.join(tempDir, 'assets');

    // Ensure the extension uses the repo-local server (so the test validates current workspace code).
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    const repoServerPath = path.resolve(__dirname, '../../../../tools/mcp-server-jupyter');
    await config.update('serverPath', repoServerPath, vscode.ConfigurationTarget.Global);

    const ext = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
    await ext?.activate();

    // Give the server a moment to finish initializing in CI/devhost.
    await new Promise((r) => setTimeout(r, 1000));
  });

  suiteTeardown(() => {
    try {
      fs.rmSync(tempDir, { recursive: true, force: true });
    } catch {
      // Ignore cleanup errors in teardown
    }
  });

  test('Lifecycle: Referenced Asset -> Delete Cell -> Save -> Asset Deleted', async () => {
    const hex = 'a'.repeat(32);
    const assetFilename = `text_${hex}.txt`;
    const assetPath = path.join(assetsDir, assetFilename);

    // 1) Create notebook on disk that references an offloaded text asset using the stub format.
    fs.mkdirSync(assetsDir, { recursive: true });
    fs.writeFileSync(assetPath, 'hello from asset\n', 'utf8');

    const nbJson = {
      cells: [
        {
          cell_type: 'code',
          execution_count: 1,
          metadata: {},
          outputs: [
            {
              output_type: 'stream',
              name: 'stdout',
              text: `Some output\n\n>>> FULL OUTPUT (10KB, 1 lines) SAVED TO: ${assetFilename} <<<\n`,
            },
          ],
          source: ["print('hello')\n"],
        },
      ],
      metadata: {},
      nbformat: 4,
      nbformat_minor: 5,
    };

    fs.writeFileSync(notebookPath, JSON.stringify(nbJson, null, 2), 'utf8');
    assert.ok(fs.existsSync(assetPath), `Precondition: asset should exist: ${assetPath}`);

    // 2) Open notebook in VS Code.
    const uri = vscode.Uri.file(notebookPath);
    const doc = await vscode.workspace.openNotebookDocument(uri);
    await vscode.window.showNotebookDocument(doc);

    // 3) Delete the cell (simulating user action).
    const deleteEdit = new vscode.WorkspaceEdit();
    deleteEdit.set(uri, [vscode.NotebookEdit.deleteCells(new vscode.NotebookRange(0, 1))]);
    await vscode.workspace.applyEdit(deleteEdit);

    // 4) Save notebook; the extension should trigger GC on save.
    await doc.save();

    // 5) Verify the backing asset file is deleted.
    const timeoutMs = 15000;
    const start = Date.now();

    while (Date.now() - start < timeoutMs) {
      if (!fs.existsSync(assetPath)) {
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }

    assert.strictEqual(fs.existsSync(assetPath), false, 'Asset file should be deleted after save-triggered GC');
  });
});
