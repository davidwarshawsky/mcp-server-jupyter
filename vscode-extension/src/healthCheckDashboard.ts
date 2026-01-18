import * as vscode from 'vscode';
import { McpClient } from './mcpClient';

/**
 * Week 2: Health Check Dashboard
 * Provides detailed status information in a webview panel
 */
export class HealthCheckDashboard {
  private panel: vscode.WebviewPanel | undefined;
  private updateInterval: NodeJS.Timeout | undefined;

  constructor(private mcpClient: McpClient) {}

  /**
   * Show or focus the health check dashboard
   */
  public show(): void {
    if (this.panel) {
      this.panel.reveal();
      return;
    }

    this.panel = vscode.window.createWebviewPanel(
      'mcpHealthCheck',
      'MCP Server Health',
      vscode.ViewColumn.Two,
      {
        enableScripts: true,
        retainContextWhenHidden: true
      }
    );

    this.panel.webview.html = this.getWebviewContent();

    // Handle messages from webview
    this.panel.webview.onDidReceiveMessage(async (message) => {
      switch (message.command) {
        case 'restart':
          await vscode.commands.executeCommand('mcp-jupyter.restartServer');
          break;
        case 'logs':
          this.mcpClient.getOutputChannel().show();
          break;
        case 'test':
          await vscode.commands.executeCommand('mcp-jupyter.testConnection');
          break;
      }
    });

    // Update dashboard every 2 seconds
    this.updateInterval = setInterval(() => {
      if (this.panel) {
        this.updateDashboard();
      }
    }, 2000);

    this.panel.onDidDispose(() => {
      this.panel = undefined;
      if (this.updateInterval) {
        clearInterval(this.updateInterval);
        this.updateInterval = undefined;
      }
    });

    // Initial update
    this.updateDashboard();
  }

  /**
   * Update dashboard with current status
   */
  private async updateDashboard(): Promise<void> {
    if (!this.panel) return;

    try {
      const status = this.mcpClient.getStatus();
      const connectionState = this.mcpClient.getConnectionState();
      
      // Try to get additional info
      let environments: any[] = [];
      let error: string | undefined;
      
      if (status === 'running' && connectionState === 'connected') {
        try {
          environments = await Promise.race([
            this.mcpClient.listEnvironments(),
            new Promise<any[]>((_, reject) => 
              setTimeout(() => reject(new Error('Timeout')), 3000)
            )
          ]);
        } catch (e) {
          error = e instanceof Error ? e.message : String(e);
        }
      }

      const data = {
        status,
        connectionState,
        environments: environments.length,
        error,
        timestamp: new Date().toLocaleTimeString()
      };

      this.panel.webview.postMessage({ type: 'update', data });
    } catch (error) {
      console.error('Failed to update health dashboard:', error);
    }
  }

  /**
   * Get webview HTML content
   */
  private getWebviewContent(): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Server Health</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            color: var(--vscode-foreground);
            background-color: var(--vscode-editor-background);
            padding: 20px;
            margin: 0;
        }
        
        .status-card {
            background: var(--vscode-editor-background);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        
        .status-header {
            display: flex;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .status-icon {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            margin-right: 15px;
        }
        
        .status-icon.running {
            background-color: #4caf50;
            color: white;
        }
        
        .status-icon.stopped {
            background-color: #f44336;
            color: white;
        }
        
        .status-icon.starting {
            background-color: #ff9800;
            color: white;
        }
        
        .status-title {
            font-size: 24px;
            font-weight: bold;
        }
        
        .status-subtitle {
            color: var(--vscode-descriptionForeground);
            font-size: 14px;
        }
        
        .metric-row {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid var(--vscode-panel-border);
        }
        
        .metric-row:last-child {
            border-bottom: none;
        }
        
        .metric-label {
            color: var(--vscode-descriptionForeground);
            font-weight: 500;
        }
        
        .metric-value {
            font-weight: bold;
        }
        
        .metric-value.success {
            color: #4caf50;
        }
        
        .metric-value.error {
            color: #f44336;
        }
        
        .metric-value.warning {
            color: #ff9800;
        }
        
        .error-message {
            background-color: var(--vscode-inputValidation-errorBackground);
            border: 1px solid var(--vscode-inputValidation-errorBorder);
            color: var(--vscode-inputValidation-errorForeground);
            padding: 10px;
            border-radius: 4px;
            margin-top: 10px;
        }
        
        .timestamp {
            text-align: right;
            color: var(--vscode-descriptionForeground);
            font-size: 12px;
            margin-top: 10px;
        }
        
        .action-buttons {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        
        button {
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }
        
        button:hover {
            background-color: var(--vscode-button-hoverBackground);
        }
        
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .loading {
            animation: pulse 1.5s ease-in-out infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
    </style>
</head>
<body>
    <div class="status-card">
        <div class="status-header">
            <div id="statusIcon" class="status-icon stopped">
                ⏸️
            </div>
            <div>
                <div id="statusTitle" class="status-title">Server Status: Unknown</div>
                <div id="statusSubtitle" class="status-subtitle">Checking connection...</div>
            </div>
        </div>
        
        <div id="metrics">
            <div class="metric-row">
                <span class="metric-label">Server Process</span>
                <span id="serverStatus" class="metric-value">Unknown</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">WebSocket Connection</span>
                <span id="connectionStatus" class="metric-value">Unknown</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Python Environments</span>
                <span id="environmentCount" class="metric-value">—</span>
            </div>
        </div>
        
        <div id="errorContainer" style="display: none;">
            <div class="error-message" id="errorMessage"></div>
        </div>
        
        <div class="action-buttons">
            <button onclick="restartServer()">Restart Server</button>
            <button onclick="showLogs()">Show Logs</button>
            <button onclick="testConnection()">Test Connection</button>
        </div>
        
        <div class="timestamp">
            Last updated: <span id="timestamp" class="loading">—</span>
        </div>
    </div>
    
    <script>
        const vscode = acquireVsCodeApi();
        
        window.addEventListener('message', event => {
            const message = event.data;
            
            if (message.type === 'update') {
                updateStatus(message.data);
            }
        });
        
        function updateStatus(data) {
            const statusIcon = document.getElementById('statusIcon');
            const statusTitle = document.getElementById('statusTitle');
            const statusSubtitle = document.getElementById('statusSubtitle');
            const serverStatus = document.getElementById('serverStatus');
            const connectionStatus = document.getElementById('connectionStatus');
            const environmentCount = document.getElementById('environmentCount');
            const errorContainer = document.getElementById('errorContainer');
            const errorMessage = document.getElementById('errorMessage');
            const timestamp = document.getElementById('timestamp');
            
            // Update status icon and title
            statusIcon.className = 'status-icon ' + data.status;
            
            if (data.status === 'running') {
                statusIcon.textContent = '✅';
                statusTitle.textContent = 'Server Status: Running';
                statusSubtitle.textContent = 'MCP server is operational';
            } else if (data.status === 'starting') {
                statusIcon.textContent = '🔄';
                statusTitle.textContent = 'Server Status: Starting';
                statusSubtitle.textContent = 'Please wait...';
            } else {
                statusIcon.textContent = '⏸️';
                statusTitle.textContent = 'Server Status: Stopped';
                statusSubtitle.textContent = 'Server is not running';
            }
            
            // Update metrics
            serverStatus.textContent = data.status;
            serverStatus.className = 'metric-value ' + 
                (data.status === 'running' ? 'success' : 
                 data.status === 'starting' ? 'warning' : 'error');
            
            connectionStatus.textContent = data.connectionState;
            connectionStatus.className = 'metric-value ' + 
                (data.connectionState === 'connected' ? 'success' : 
                 data.connectionState === 'connecting' ? 'warning' : 'error');
            
            if (data.environments > 0) {
                environmentCount.textContent = data.environments + ' found';
                environmentCount.className = 'metric-value success';
            } else {
                environmentCount.textContent = '—';
                environmentCount.className = 'metric-value';
            }
            
            // Show error if present
            if (data.error) {
                errorContainer.style.display = 'block';
                errorMessage.textContent = data.error;
            } else {
                errorContainer.style.display = 'none';
            }
            
            // Update timestamp
            timestamp.textContent = data.timestamp;
            timestamp.classList.remove('loading');
        }
        
        function restartServer() {
            vscode.postMessage({ command: 'restart' });
        }
        
        function showLogs() {
            vscode.postMessage({ command: 'logs' });
        }
        
        function testConnection() {
            vscode.postMessage({ command: 'test' });
        }
    </script>
</body>
</html>`;
  }

  /**
   * Dispose resources
   */
  public dispose(): void {
    if (this.updateInterval) {
      clearInterval(this.updateInterval);
    }
    if (this.panel) {
      this.panel.dispose();
    }
  }
}
