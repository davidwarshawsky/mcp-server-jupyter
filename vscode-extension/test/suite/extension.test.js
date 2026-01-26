"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
const assert = __importStar(require("assert"));
const vscode = __importStar(require("vscode"));
suite('Extension Activation Test Suite', () => {
    vscode.window.showInformationMessage('Start extension activation tests.');
    test('Extension should be present', () => {
        const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
        assert.ok(extension, 'Extension should be installed');
    });
    test('Extension should activate', async () => {
        const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
        assert.ok(extension, 'Extension not found');
        await extension.activate();
        assert.strictEqual(extension.isActive, true, 'Extension should be active');
    });
    test('Commands should be registered', async () => {
        const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
        assert.ok(extension);
        await extension.activate();
        const commands = await vscode.commands.getCommands(true);
        const expectedCommands = [
            'mcp-jupyter.selectEnvironment',
            'mcp-jupyter.restartServer',
            'mcp-jupyter.showServerLogs',
        ];
        for (const cmd of expectedCommands) {
            assert.ok(commands.includes(cmd), `Command ${cmd} should be registered`);
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
        assert.strictEqual(config.get('pollingInterval'), 500, 'Default polling interval should be 500ms');
        assert.strictEqual(config.get('autoRestart'), true, 'Auto-restart should be enabled by default');
    });
});
//# sourceMappingURL=extension.test.js.map