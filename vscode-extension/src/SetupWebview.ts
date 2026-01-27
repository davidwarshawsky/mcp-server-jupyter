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
                    } else if (message.command === 'validate-python-path') {
                        // Forward validation request to the extension backend
                        vscode.commands.executeCommand('mcp-jupyter.validatePythonPath', message.path).then(isValid => {
                            this.panel?.webview.postMessage({ command: 'validation-result', result: isValid });
                        });
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
        const anImg = this.panel?.webview.asWebviewUri(vscode.Uri.file(path.join(this.context.extensionPath, 'media', 'setup-step-1.svg')));
        const anotherImg = this.panel?.webview.asWebviewUri(vscode.Uri.file(path.join(this.context.extensionPath, 'media', 'setup-step-2.svg')));
        const finalImg = this.panel?.webview.asWebviewUri(vscode.Uri.file(path.join(this.context.extensionPath, 'media', 'setup-step-3.svg')));

        return `<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>MCP Jupyter Setup</title>
                <style>
                    body { font-family: var(--vscode-font-family); color: var(--vscode-editor-foreground); background-color: var(--vscode-editor-background); padding: 20px; }
                    .option { border: 1px solid var(--vscode-button-border, transparent); }
                    .option[aria-selected="true"] { border: 1px solid var(--vscode-focusBorder); }
                    .option:focus { outline: 1px solid var(--vscode-focusBorder); }
                    .input-group { margin-top: 10px; display: flex; gap: 10px; }
                    #status { white-space: pre-wrap; }
                    .validation-status { font-size: 12px; }
                    .validation-status.success { color: var(--vscode-terminal-ansiGreen); }
                    .validation-status.error { color: var(--vscode-terminal-ansiRed); }
                </style>
            </head>
            <body>
                <!-- ... (rest of the HTML is the same) ... -->
                <div class="options">
                    <div class="option" role="button" tabindex="0" data-mode="managed" aria-label="Automatic Setup, Recommended">
                        <h3>🚀 Automatic Setup (Recommended)</h3>
                        <p>Creates a self-contained environment. No configuration needed.</p>
                    </div>
                    <div class="option" role="button" tabindex="0" data-mode="existing" aria-label="Use an Existing Python Environment">
                        <h3>🐍 Use an Existing Python Environment</h3>
                        <p>Use a Python environment you already have.</p>
                        <div class="input-group" style="display: none;">
                            <input type="text" id="pythonPath" placeholder="Enter path to Python executable">
                            <button id="validatePath">Validate</button>
                            <span id="validationStatus" class="validation-status"></span>
                        </div>
                    </div>
                    <!-- ... -->
                </div>
                <button id="startSetup">Start Setup</button>
                <div id="status"></div>
                <script>
                    const vscode = acquireVsCodeApi();
                    let selectedMode = 'managed'; // Default selection

                    function handleSelection(element) {
                        document.querySelectorAll('.option').forEach(opt => opt.setAttribute('aria-selected', 'false'));
                        element.setAttribute('aria-selected', 'true');
                        selectedMode = element.dataset.mode;
                        document.querySelectorAll('.input-group').forEach(ig => ig.style.display = 'none');
                        const inputGroup = element.querySelector('.input-group');
                        if (inputGroup) {
                            inputGroup.style.display = 'flex';
                        }
                    }

                    document.querySelectorAll('.option').forEach(option => {
                        option.addEventListener('click', e => handleSelection(e.currentTarget));
                        option.addEventListener('keydown', e => {
                            if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault();
                                handleSelection(e.currentTarget);
                            }
                        });
                    });

                    document.getElementById('validatePath').addEventListener('click', () => {
                        const path = document.getElementById('pythonPath').value;
                        document.getElementById('validationStatus').textContent = 'Validating...';
                        vscode.postMessage({ command: 'validate-python-path', path });
                    });

                    window.addEventListener('message', event => {
                        const message = event.data;
                        if (message.command === 'validation-result') {
                            const statusEl = document.getElementById('validationStatus');
                            if(message.result) {
                                statusEl.textContent = '✅ Valid';
                                statusEl.className = 'validation-status success';
                            } else {
                                statusEl.textContent = '❌ Invalid Environment';
                                statusEl.className = 'validation-status error';
                            }
                        }
                        // ... status updates
                    });
                    
                    // Set initial state
                    handleSelection(document.querySelector('.option[data-mode="managed"]'));
                </script>
            </body>
            </html>`;
    }
}
