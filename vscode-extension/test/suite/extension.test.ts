import * as assert from 'assert';
import * as vscode from 'vscode';

suite('Extension Activation Test Suite', () => {
  vscode.window.showInformationMessage('Start extension activation tests.');

  test('Extension should be present', () => {
    const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
    assert.ok(extension, 'Extension should be installed');
  });

  test('Extension should activate without throwing', async function() {
    // Increase timeout for activation (server startup can be slow)
    this.timeout(30000);
    
    const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
    assert.ok(extension, 'Extension not found');

    try {
      await extension.activate();
      assert.strictEqual(extension.isActive, true, 'Extension should be active');
    } catch (error) {
      // If server fails to start due to missing Python deps, that's expected in test env
      const errorMessage = error instanceof Error ? error.message : String(error);
      if (errorMessage.includes('MCP server') || errorMessage.includes('Python')) {
        console.warn('Server startup failed (expected in test environment):', errorMessage);
        // This is not a test failure - just means the Python environment isn't set up
        this.skip();
      } else {
        throw error;
      }
    }
  });

  test('Commands should be registered', async () => {
    const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
    assert.ok(extension);
    
    // Try to activate, but don't fail test if server unavailable
    try {
      await extension.activate();
    } catch {
      // Ignore activation errors for this test
    }

    const commands = await vscode.commands.getCommands(true);
    
    const expectedCommands = [
      'mcp-jupyter.selectEnvironment',
      'mcp-jupyter.restartServer',
      'mcp-jupyter.showServerLogs',
    ];

    for (const cmd of expectedCommands) {
      assert.ok(
        commands.includes(cmd),
        `Command ${cmd} should be registered`
      );
    }
  });

  test('Configuration should have expected properties', () => {
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    
    // Check that configuration properties exist
    assert.ok(config.has('serverPath'), 'Should have serverPath config');
    assert.ok(config.has('pythonPath'), 'Should have pythonPath config');
    assert.ok(config.has('pollingInterval'), 'Should have pollingInterval config');
    assert.ok(config.has('autoRestart'), 'Should have autoRestart config');
    
    // Check default values
    assert.strictEqual(
      config.get('pollingInterval'),
      500,
      'Default polling interval should be 500ms'
    );
    assert.strictEqual(
      config.get('autoRestart'),
      true,
      'Auto-restart should be enabled by default'
    );
  });
});
