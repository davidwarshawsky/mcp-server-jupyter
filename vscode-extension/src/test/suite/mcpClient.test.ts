import * as assert from 'assert';
import * as vscode from 'vscode';
import * as sinon from 'sinon';
import WebSocket, { WebSocketServer } from 'ws';
import { MCPClient } from '../../mcpClient';

suite('McpClient Test Suite', () => {
    let client: MCPClient;
    let outputChannelStub: any;

    setup(() => {
        // Mock the OutputChannel so we don't spam UI
        outputChannelStub = {
            append: sinon.stub(),
            appendLine: sinon.stub(),
            replace: sinon.stub(),
            clear: sinon.stub(),
            show: sinon.stub(),
            hide: sinon.stub(),
            dispose: sinon.stub(),
            name: 'Mock MCP'
        };
        
        // Stub window.createOutputChannel
        sinon.stub(vscode.window, 'createOutputChannel').returns(outputChannelStub);
        
        client = new MCPClient();
    });

    teardown(() => {
        sinon.restore();
    });

    test('runCellAsync sends correct JSON-RPC request', async () => {
        // Stub the internal process.stdin.write
        // Since process is private, we stub the callTool method or hack prototype
        // Better: Integration test or use 'any' casting for white-box testing
        
        // Let's test the public API behavior via callTool stub
        const callToolStub = sinon.stub(client as any, 'callTool').resolves({ task_id: '123' });
        
        // Explicitly assert arguments with type casting match
        const taskId = await client.runCellAsync('/tmp/test.ipynb', 0, 'print("hi")');
        
        assert.strictEqual(taskId, '123');
        assert.ok(callToolStub.calledWith('run_cell_async', sinon.match({
            notebook_path: '/tmp/test.ipynb',
            index: 0,
            code_override: 'print("hi")'
        })));
    });

    test('notifications emit events', () => {
        let eventFired = false;
        client.onNotification(e => {
            eventFired = true;
            assert.strictEqual(e.method, 'notebook/output');
        });

        // Simulate incoming data
        // Access private handleResponse via cast
        (client as any).handleResponse({
            jsonrpc: '2.0',
            method: 'notebook/output',
            params: { text: 'hello' }
        });

        assert.strictEqual(eventFired, true);
    });

    test('connectWebSocket negotiates MCP subprotocol', async () => {
        // Create a WS server that *requires* the 'mcp' subprotocol.
        const wss = new WebSocketServer({
            port: 0,
            handleProtocols: (protocols) => {
                // In ws@8, protocols is a Set<string>
                return protocols.has('mcp') ? 'mcp' : false;
            }
        });

        const address = wss.address();
        assert.ok(address && typeof address === 'object', 'Expected server to be listening');
        const port = (address as any).port as number;

        let negotiated: string | undefined;
        wss.on('connection', (socket: WebSocket) => {
            negotiated = socket.protocol;
            // Close immediately; we only care about handshake negotiation.
            socket.close();
        });

        try {
            await (client as any).connectWebSocket(`ws://127.0.0.1:${port}/ws`, 3, 50);
            assert.strictEqual(negotiated, 'mcp');
        } finally {
            try {
                (client as any).ws?.close();
            } catch {
                // ignore
            }
            await new Promise<void>((resolve) => wss.close(() => resolve()));
        }
    });
});
