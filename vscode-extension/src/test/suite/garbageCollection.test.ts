import * as assert from 'assert';
import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';

// Import the shared test helper (different path since we're in src/test/suite)
// We need to reference the compiled version in out/test/suite
async function spawnTestServer(): Promise<{ proc: any; port: number }> {
    const cp = await import('child_process');
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    const serverPath = path.resolve(__dirname, '../../../../../tools/mcp-server-jupyter');
    const rootDir = path.resolve(__dirname, '../../../../../');
    const venvPython = process.platform === 'win32'
        ? path.join(rootDir, '.venv', 'Scripts', 'python.exe')
        : path.join(rootDir, '.venv', 'bin', 'python');

    await config.update('serverPath', serverPath, vscode.ConfigurationTarget.Global);

    if (fs.existsSync(venvPython)) {
        console.log(`[GC Test] Using .venv Python: ${venvPython}`);
        await config.update('pythonPath', venvPython, vscode.ConfigurationTarget.Global);
    } else {
        await config.update('pythonPath', 'python3', vscode.ConfigurationTarget.Global);
    }

    console.log(`[GC Test] Spawning server at ${serverPath}`);
    const serverSpawn = cp.spawn(venvPython, ['-m', 'src.main', '--transport', 'websocket', '--port', '0', '--idle-timeout', '600'], { cwd: serverPath });

    let allStderr = '';
    const assignedPort = await new Promise<number>((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Timed out waiting for server port')), 10000);
        serverSpawn.stderr?.on('data', (data: any) => {
            const txt = data.toString();
            allStderr += txt;
            console.log(`[GC Server stderr] ${txt.trim()}`);
            const m = txt.match(/\[MCP_PORT\]:\s*(\d+)/);
            if (m) {
                clearTimeout(timeout);
                resolve(parseInt(m[1], 10));
            }
        });
        serverSpawn.on('error', (err: any) => { clearTimeout(timeout); reject(err); });
        serverSpawn.on('exit', (code: number) => {
            if (code !== null) { clearTimeout(timeout); reject(new Error(`Server exited with code ${code}`)); }
        });
    });

    console.log(`[GC Test] Server started on port ${assignedPort}`);
    await config.update('serverMode', 'connect', vscode.ConfigurationTarget.Global);
    await config.update('remotePort', assignedPort, vscode.ConfigurationTarget.Global);

    const ext = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
    await ext?.activate();
    await vscode.commands.executeCommand('mcp-jupyter.restartServer');
    await new Promise(resolve => setTimeout(resolve, 2000));

    return { proc: serverSpawn, port: assignedPort };
}

suite('Garbage Collection Integration Test', function () {
  this.timeout(60000); // 60s timeout

  let tempDir: string;
  let notebookPath: string;
  let assetsDir: string;
  let serverProc: any = null;

  suiteSetup(async () => {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-jupyter-gc-'));
    notebookPath = path.join(tempDir, 'gc_test.ipynb');
    assetsDir = path.join(tempDir, 'assets');

    // Spawn the test server and configure extension
    const { proc, port } = await spawnTestServer();
    serverProc = proc;
    console.log(`[GC Test] Server running on port ${port}`);
  });

  suiteTeardown(() => {
    if (serverProc) {
      try { serverProc.kill('SIGTERM'); } catch {}
    }
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
