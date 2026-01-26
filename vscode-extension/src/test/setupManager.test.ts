import * as assert from 'assert';
import * as vscode from 'vscode';
import * as path from 'path';
import { SetupManager } from '../setupManager';

suite('SetupManager', () => {
  test('getManagedVenvPath returns path in globalStorage', async () => {
    const fakeContext: any = {
      globalStorageUri: vscode.Uri.file(path.join(__dirname, 'tmp-global')),
      storageUri: vscode.Uri.file(path.join(__dirname, 'tmp-storage')),
      extensionPath: path.resolve(__dirname, '..'),
      globalState: {
        get: (k: string, d: any) => d,
        update: async (k: string, v: any) => {}
      }
    };

    const manager = new SetupManager(fakeContext as any);
    const venv = manager.getManagedVenvPath();
    assert.ok(venv.endsWith('mcp-venv'), `Unexpected venv path: ${venv}`);
  });
});
