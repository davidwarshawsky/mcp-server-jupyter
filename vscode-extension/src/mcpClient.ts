import * as vscode from 'vscode';
import { spawn } from 'child_process';

// Define specific types for server communication
interface MCPResponse {
    jsonrpc: string;
    id?: number | string;
    result?: any;
    error?: any;
    method?: string;
    params?: any;
}

interface MCPRequest {
    jsonrpc: string;
    id: number | string;
    method: string;
    params?: any;
}

export class MCPClient {
    private process: any = null;
    private session_id: string;
    private requestQueue = new Map<string | number, (response: MCPResponse) => void>();
    private static client: MCPClient | null = null;
    private outputChannel: vscode.OutputChannel;
    private status: 'stopped' | 'starting' | 'running' = 'stopped';
    private connectionState: 'disconnected' | 'connecting' | 'connected' = 'disconnected';
    private notificationHandlers: ((event: { method: string, params: any }) => void)[] = [];

    private constructor(pythonPath: string, sessionId: string) {
        this.session_id = sessionId;
        this.outputChannel = vscode.window.createOutputChannel('MCP Jupyter');

        // Spawn the MCP server process
        this.process = spawn(pythonPath, ['-m', 'mcp_server_jupyter'], {
            stdio: ['pipe', 'pipe', 'pipe'],
            env: { ...process.env, MCP_SESSION_ID: sessionId }
        });

        this.process.stdout.on('data', (data: Buffer) => {
            const lines = data.toString().split('\n');
            for (const line of lines) {
                if (line.trim()) {
                    try {
                        const response: MCPResponse = JSON.parse(line);
                        if (response.id && this.requestQueue.has(response.id)) {
                            const callback = this.requestQueue.get(response.id)!;
                            callback(response);
                            this.requestQueue.delete(response.id);
                        } else if (response.method && response.params) {
                            // Notification
                            this.notificationHandlers.forEach(handler => 
                                handler({ method: response.method!, params: response.params })
                            );
                        }
                    } catch (e) {
                        console.error('Failed to parse MCP response:', e);
                    }
                }
            }
        });

        this.process.stderr.on('data', (data: Buffer) => {
            this.outputChannel.appendLine(data.toString());
        });

        this.process.on('close', (code: number) => {
            console.log('MCP server process closed with code:', code);
            this.connectionState = 'disconnected';
            this.status = 'stopped';
            MCPClient.client = null;
        });

        this.connectionState = 'connected';
        this.status = 'running';
    }

    public static getInstance(pythonPath: string, sessionId: string): MCPClient {
        if (!MCPClient.client) {
            MCPClient.client = new MCPClient(pythonPath, sessionId);
        }
        return MCPClient.client;
    }

    public onNotification(handler: (event: { method: string, params: any }) => void): void {
        this.notificationHandlers.push(handler);
    }

    private sendRequest(request: MCPRequest): Promise<MCPResponse> {
        return new Promise((resolve, reject) => {
            const requestJson = JSON.stringify(request) + '\n';
            this.process.stdin.write(requestJson);
            this.requestQueue.set(request.id, resolve);
            
            // Timeout
            setTimeout(() => {
                this.requestQueue.delete(request.id);
                reject(new Error('Request timeout'));
            }, 30000);
        });
    }

    public async runCellAsync(notebookPath: string, index: number, code: string, taskId: string): Promise<string> {
        const response = await this.sendRequest({
            jsonrpc: '2.0',
            id: taskId,
            method: 'tools/call',
            params: {
                name: 'run_cell_async',
                arguments: {
                    notebook_path: notebookPath,
                    cell_index: index,
                    code: code,
                    exec_id: taskId
                }
            }
        });
        
        // The server tool returns the kernel_msg_id
        return response.result?.content?.[0]?.text || response.result;
    }

    public close(): void {
        if (this.process) {
            this.process.kill();
        }
    }

    // Stub methods for compatibility - these will be replaced with proper MCP tool calls
    public async startKernel(notebookPath: string, venvPath?: string): Promise<void> {
        // TODO: Implement via MCP tool call
    }

    public async stopKernel(notebookPath: string): Promise<void> {
        // TODO: Implement via MCP tool call
    }

    public async cancelExecution(notebookPath: string, taskId?: string): Promise<void> {
        // TODO: Implement via MCP tool call
    }

    public async submitInput(notebookPath: string, input: string): Promise<void> {
        // TODO: Implement via MCP tool call
    }

    public async callTool(name: string, args: any): Promise<any> {
        const response = await this.sendRequest({
            jsonrpc: '2.0',
            id: `tool_${Date.now()}`,
            method: 'tools/call',
            params: {
                name: name,
                arguments: args
            }
        });
        return response.result;
    }

    public getStatus(): 'stopped' | 'starting' | 'running' {
        return this.status;
    }

    public async checkKernelResources(notebookPath: string): Promise<any> {
        // TODO: Implement via MCP tool call
        return {};
    }

    public async isKernelBusy(notebookPath: string): Promise<boolean> {
        // TODO: Implement via MCP tool call
        return false;
    }

    public async getVariableManifest(notebookPath: string): Promise<any> {
        // TODO: Implement via MCP tool call
        return {};
    }

    public async persistExecutionState(notebookPath: string, cellIds: string[]): Promise<void> {
        // TODO: Implement via MCP tool call
    }

    public async restoreExecutionState(): Promise<any> {
        // TODO: Implement via MCP tool call
        return {};
    }

    public async detectSyncNeeded(notebookPath: string): Promise<any> {
        // TODO: Implement via MCP tool call
        return {};
    }

    public async syncStateFromDisk(notebookPath: string): Promise<void> {
        // TODO: Implement via MCP tool call
    }

    public async reconcileExecutions(ids: string[], notebookPath: string): Promise<void> {
        // TODO: Implement via MCP tool call
    }

    public async getAssetContent(assetPath: string): Promise<any> {
        // TODO: Implement via MCP tool call
        return {};
    }
}
