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

    private constructor(serverUri: string, sessionId: string, kernel: MCPKernel) {
        this.session_id = sessionId;
        this.kernel = kernel;
        this.ws = new WebSocket(`${serverUri}/ws/${this.session_id}`);

        this.ws.on('open', () => {
            console.log('Connected to MCP server');
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
            MCPClient.client = null; // Allow re-creation
        });

        this.ws.on('error', (error: Error) => {
            console.error('WebSocket error:', error);
            // [DUH FIX: WHERE ARE MY LOGS] Add "Show Logs" button on errors
            const errorMsg = error.message.toLowerCase();
            if (errorMsg.includes('error') || errorMsg.includes('traceback') || errorMsg.includes('failed')) {
                vscode.window.showErrorMessage(
                    `MCP Server Error: ${error.message}`,
                    'Show Logs'
                ).then(choice => {
                    if (choice === 'Show Logs') {
                        vscode.commands.executeCommand('mcp-jupyter.showServerLogs');
                    }
                });
            } else {
                vscode.window.showErrorMessage(`WebSocket Error: ${error.message}`);
            }
            MCPClient.client = null; // Allow re-creation
        });
    }

    public static getInstance(serverUri: string, sessionId: string, kernel: MCPKernel): MCPClient {
        if (!MCPClient.client) {
            MCPClient.client = new MCPClient(serverUri, sessionId, kernel);
        }
        return MCPClient.client;
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

            // Timeout for the request
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
        return response.data; // Assuming the server sends back a data field
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

    /**
     * Executes a DuckDB query on the server using parameterized queries to prevent injection.
     * @param query The SQL query string, with '?' for placeholders.
     * @param params An array of parameters to substitute for the placeholders.
     * @returns The query result from the server.
     */
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
