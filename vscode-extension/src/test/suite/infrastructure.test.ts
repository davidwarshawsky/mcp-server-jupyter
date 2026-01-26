import * as assert from 'assert';
import * as vscode from 'vscode';
import * as sinon from 'sinon';

suite('Infrastructure Unit Tests', () => {
    let outputChannelStub: any;

    setup(() => {
        outputChannelStub = {
            append: sinon.stub(),
            appendLine: sinon.stub(),
            show: sinon.stub(),
            dispose: sinon.stub()
        };
        sinon.stub(vscode.window, 'createOutputChannel').returns(outputChannelStub);
    });

    teardown(() => {
        sinon.restore();
    });

    test('Port Parsing Regex matches standard output', async () => {
        // This tests the exact logic used in mcpClient.ts to read stderr
        const stderrText = `
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
[MCP_PORT]: 45123
INFO:     Application startup complete.
`;
        const m = stderrText.match(/\[MCP_PORT\]:\s*(\d+)/);
        
        assert.ok(m, 'Regex failed to find port');
        assert.strictEqual(m![1], '45123');
    });

    test('Path Normalization handles Windows Backslashes', () => {
        const windowsPath = "assets\\image.png";
        const normalized = windowsPath.replace(/\\/g, '/');
        
        assert.strictEqual(normalized, "assets/image.png");
        assert.ok(normalized.startsWith('assets/'));
    });

    test('Path Normalization handles Mixed Paths', () => {
        const mixedPath = "projects\\deep_learning/assets\\plot.png";
        const normalized = mixedPath.replace(/\\/g, '/');
        
        assert.strictEqual(normalized, "projects/deep_learning/assets/plot.png");
    });
});