import * as vscode from 'vscode';
import { WebSocket } from 'ws';
import { MCPKernel } from './mcpKernel';

// Define specific types for server communication
interface MCPResponse {
    request_id: string;
    type: string;
    message?: string;
    data?: unknown;
}

interface ExecuteCodeRequest {
    type: 'execute_code';
    code: string;
    cell_id: string;
    request_id?: string;
}

interface HandoffRequest {
    type: 'request_handoff' | 'release_handoff';
    request_id?: string;
}

interface DuckDBQueryRequest {
    type: 'execute_duckdb_query';
    query: string;
    params: unknown[];
    request_id?: string;
}

type MCPRequest = ExecuteCodeRequest | HandoffRequest | DuckDBQueryRequest;

export class MCPClient {
    private ws: WebSocket | null = null;
    private session_id: string;
    private kernel: MCPKernel;
    private requestQueue: Map<string, (response: MCPResponse) => void> = new Map();
    private static client: MCPClient | null = null;
    private outputChannel: vscode.OutputChannel;
    private status: 'stopped' | 'starting' | 'running' = 'stopped';
    private connectionState: 'disconnected' | 'connecting' | 'connected' = 'disconnected';

    private constructor(serverUri: string, sessionId: string, kernel: MCPKernel) {
        this.session_id = sessionId;
        this.kernel = kernel;
        this.outputChannel = vscode.window.createOutputChannel('MCP Jupyter');
        this.ws = new WebSocket(`${serverUri}/ws/${this.session_id}`);

        this.ws.on('open', () => {
            console.log('Connected to MCP server');
            this.connectionState = 'connected';
            this.status = 'running';
        });

        this.ws.on('message', (data: Buffer | string) => {
            const response: MCPResponse = JSON.parse(data.toString());
            const { request_id } = response;

            if (this.requestQueue.has(request_id)) {
                const callback = this.requestQueue.get(request_id);
                if (callback) {
                    callback(response);
                }
                this.requestQueue.delete(request_id);
            }
        });

        this.ws.on('close', () => {
            console.log('Disconnected from MCP server');
            this.connectionState = 'disconnected';
            this.status = 'stopped';
            MCPClient.client = null; // Allow re-creation
        });

        this.ws.on('error', (error: Error) => {
            console.error('WebSocket error:', error);
            this.outputChannel.appendLine(`WebSocket Error: ${error.message}`);
            vscode.window.showErrorMessage(`MCP Server Error: ${error.message}`, 'Show Logs').then(choice => {
                if (choice === 'Show Logs') {
                    this.outputChannel.show();
                }
            });
            this.connectionState = 'disconnected';
            this.status = 'stopped';
            MCPClient.client = null; // Allow re-creation
        });
    }

    public static getInstance(serverUri: string, sessionId: string, kernel: MCPKernel): MCPClient {
        if (!MCPClient.client) {
            MCPClient.client = new MCPClient(serverUri, sessionId, kernel);
        }
        return MCPClient.client;
    }

    public start(): Promise<void> {
        this.status = 'starting';
        this.connectionState = 'connecting';
        // The connection is initiated in the constructor, so we just need to wait for it to open.
        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                if (this.connectionState !== 'connected') {
                    reject(new Error('Connection timeout'));
                }
            }, 10000);

            this.ws.on('open', () => {
                clearTimeout(timeout);
                resolve();
            });
        });
    }

    public getStatus(): 'stopped' | 'starting' | 'running' {
        return this.status;
    }

    public getConnectionState(): 'disconnected' | 'connecting' | 'connected' {
        return this.connectionState;
    }

    public getOutputChannel(): vscode.OutputChannel {
        return this.outputChannel;
    }

    public listEnvironments(): Promise<any[]> {
        // This is a placeholder. A real implementation would send a request to the server.
        return Promise.resolve(["Python 3.8", "Python 3.9"]);
    }

    private generateRequestId(): string {
        return `req_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    }

    private sendRequest(payload: MCPRequest): Promise<MCPResponse> {
        return new Promise((resolve, reject) => {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
                return reject(new Error('WebSocket is not connected.'));
            }

            const request_id = this.generateRequestId();
            payload.request_id = request_id;

            this.requestQueue.set(request_id, (response) => {
                if (response.type === 'error') {
                    reject(new Error(response.message));
                } else {
                    resolve(response);
                }
            });

            this.ws.send(JSON.stringify(payload));

            setTimeout(() => {
                if (this.requestQueue.has(request_id)) {
                    this.requestQueue.delete(request_id);
                    reject(new Error('Request timed out'));
                }
            }, 30000); // 30-second timeout
        });
    }

    public async executeCode(code: string, cellId: string): Promise<unknown> {
        const response = await this.sendRequest({
            type: 'execute_code',
            code,
            cell_id: cellId
        });
        return response.data;
    }

    public async requestHandoff(): Promise<boolean> {
        const response = await this.sendRequest({ type: 'request_handoff' });
        if (response.type === 'handoff_granted') {
            this.kernel.isPrimary = true;
            return true;
        }
        return false;
    }

    public async releaseHandoff(): Promise<boolean> {
        const response = await this.sendRequest({ type: 'release_handoff' });
        if (response.type === 'handoff_released') {
            this.kernel.isPrimary = false;
            return true;
        }
        return false;
    }

    public async executeDuckDBQuery(query: string, params?: unknown[]): Promise<unknown> {
        const response = await this.sendRequest({
            type: 'execute_duckdb_query',
            query: query,
            params: params || []
        });

        return response.data;
    }

    public close(): void {
        if (this.ws) {
            this.ws.close();
        }
    }
}
