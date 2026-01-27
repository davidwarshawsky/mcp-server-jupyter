import * as vscode from 'vscode';
import * as path from 'path';

export class SetupWebview {
    private panel: vscode.WebviewPanel | undefined;
    private readonly context: vscode.ExtensionContext;
    private readonly runSetupCallback: (mode: 'managed' | 'existing' | 'remote', data?: any) => Promise<void>;

    constructor(context: vscode.ExtensionContext, runSetupCallback: (mode: 'managed' | 'existing' | 'remote', data?: any) => Promise<void>) {
        this.context = context;
        this.runSetupCallback = runSetupCallback;
    }

    public show(): void {
        if (this.panel) {
            this.panel.reveal(vscode.ViewColumn.One);
        } else {
            this.panel = vscode.window.createWebviewPanel(
                'mcpJupyterSetup',
                'MCP Jupyter Setup',
                vscode.ViewColumn.One,
                {
                    enableScripts: true,
                    localResourceRoots: [vscode.Uri.file(path.join(this.context.extensionPath, 'media'))]
                }
            );

            this.panel.webview.html = this.getWebviewContent();

            this.panel.webview.onDidReceiveMessage(
                message => {
                    if (message.command === 'start-setup') {
                        this.runSetupCallback(message.mode, message.data);
                    }
                },
                undefined,
                this.context.subscriptions
            );

            this.panel.onDidDispose(() => {
                this.panel = undefined;
            }, null, this.context.subscriptions);
        }
    }

    public updateStatus(message: string): void {
        if (this.panel) {
            this.panel.webview.postMessage({ command: 'update-status', message });
        }
    }

    private getWebviewContent(): string {
        const anImg = this.panel.webview.asWebviewUri(vscode.Uri.file(
            path.join(this.context.extensionPath, 'media', 'setup-step-1.svg')
        ));
        const anotherImg = this.panel.webview.asWebviewUri(vscode.Uri.file(
            path.join(this.context.extensionPath, 'media', 'setup-step-2.svg')
        ));
        const finalImg = this.panel.webview.asWebviewUri(vscode.Uri.file(
            path.join(this.context.extensionPath, 'media', 'setup-step-3.svg')
        ));

        return `<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>MCP Jupyter Setup</title>
                <style>
                    body { font-family: var(--vscode-font-family); color: var(--vscode-editor-foreground); background-color: var(--vscode-editor-background); padding: 20px; }
                    h1 { font-size: 24px; margin-bottom: 10px; }
                    p { font-size: 14px; margin-bottom: 20px; }
                    .steps { display: flex; justify-content: space-between; margin-bottom: 30px; }
                    .step { text-align: center; width: 30%; }
                    .step img { max-width: 100px; margin-bottom: 10px; }
                    .options { display: grid; grid-template-columns: 1fr; gap: 15px; }
                    .option { background-color: var(--vscode-button-background); padding: 15px; border-radius: 5px; cursor: pointer; border: 1px solid var(--vscode-button-border, transparent); }
                    .option:hover { background-color: var(--vscode-button-hoverBackground); }
                    .option h3 { margin: 0; font-size: 16px; } 
                    .option p { font-size: 12px; opacity: 0.8; margin-top: 5px; }
                    .input-group { margin-top: 15px; }
                    input { width: 100%; padding: 8px; border-radius: 3px; border: 1px solid var(--vscode-input-border); background-color: var(--vscode-input-background); color: var(--vscode-input-foreground); }
                    button { margin-top: 15px; padding: 10px 15px; background-color: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; border-radius: 5px; cursor: pointer; }
                    button:hover { background-color: var(--vscode-button-hoverBackground); }
                    #status { margin-top: 20px; padding: 10px; background-color: var(--vscode-input-background); border-radius: 5px; white-space: pre-wrap; font-family: var(--vscode-editor-font-family); }
                </style>
            </head>
            <body>
                <h1>Welcome to MCP Jupyter</h1>
                <p>Let's get you set up. Choose an installation option below.</p>

                <div class="steps">
                    <div class="step">
                        <img src="${anImg}" alt="Step 1: Choose Setup">
                        <p>1. Choose Setup</p>
                    </div>
                    <div class="step">
                        <img src="${anotherImg}" alt="Step 2: Install">
                        <p>2. Install</p>
                    </div>
                    <div class="step">
                        <img src="${finalImg}" alt="Step 3: Ready">
                        <p>3. Ready!</p>
                    </div>
                </div>

                <div class="options">
                    <div class="option" data-mode="managed">
                        <h3>🚀 Automatic Setup (Recommended)</h3>
                        <p>Creates a self-contained environment for MCP Jupyter. No configuration needed.</p>
                    </div>
                    <div class="option" data-mode="existing">
                        <h3>🐍 Use an Existing Python Environment</h3>
                        <p>Use a Python environment you already have. You may need to install dependencies.</p>
                        <div class="input-group" style="display: none;">
                            <input type="text" id="pythonPath" placeholder="Enter path to Python executable">
                        </div>
                    </div>
                    <div class="option" data-mode="remote">
                        <h3>☁️ Connect to a Remote Server</h3>
                        <p>Connect to an MCP Jupyter server running on another machine.</p>
                        <div class="input-group" style="display: none;">
                            <input type="text" id="host" placeholder="Enter server host">
                            <input type="text" id="port" placeholder="Enter server port">
                        </div>
                    </div>
                </div>
                
                <button id="startSetup" style="display: none;">Start Setup</button>

                <div id="status"></div>

                <script>
                    const vscode = acquireVsCodeApi();
                    let selectedMode = '';

                    document.querySelectorAll('.option').forEach(option => {
                        option.addEventListener('click', event => {
                            selectedMode = event.currentTarget.dataset.mode;
                            document.querySelectorAll('.input-group').forEach(ig => ig.style.display = 'none');
                            const inputGroup = event.currentTarget.querySelector('.input-group');
                            if (inputGroup) {
                                inputGroup.style.display = 'block';
                            }
                            document.getElementById('startSetup').style.display = 'block';
                        });
                    });

                    document.getElementById('startSetup').addEventListener('click', () => {
                        let data = {};
                        if (selectedMode === 'existing') {
                            data.pythonPath = document.getElementById('pythonPath').value;
                        } else if (selectedMode === 'remote') {
                            data.host = document.getElementById('host').value;
                            data.port = document.getElementById('port').value;
                        }
                        vscode.postMessage({ command: 'start-setup', mode: selectedMode, data: data });
                        document.querySelector('.options').style.display = 'none';
                        document.getElementById('startSetup').style.display = 'none';
                    });

                    window.addEventListener('message', event => {
                        const message = event.data;
                        const statusDiv = document.getElementById('status');
                        switch (message.command) {
                            case 'update-status':
                                statusDiv.innerHTML += message.message;
                                break;
                        }
                    });
                </script>
            </body>
            </html>`;
    }
}
