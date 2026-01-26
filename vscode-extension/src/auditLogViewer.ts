import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { McpClient } from './mcpClient';

/**
 * Week 4: Audit Log Viewer
 * Browse and filter audit logs for compliance and debugging
 */

export class AuditLogViewer {
  private panel: vscode.WebviewPanel | undefined;
  private auditLogPath: string | undefined;

  constructor(private mcpClient: McpClient) {
    // Try to find audit log path
    this.findAuditLogPath();
  }

  private async findAuditLogPath(): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) return;

    // Check common locations
    const possiblePaths = [
      path.join(workspaceFolder.uri.fsPath, '.mcp-jupyter', 'audit.log'),
      path.join(workspaceFolder.uri.fsPath, 'audit.log'),
      path.join(os.homedir(), '.mcp-jupyter', 'audit.log')
    ];

    for (const p of possiblePaths) {
      if (fs.existsSync(p)) {
        this.auditLogPath = p;
        break;
      }
    }
  }

  public async show(): Promise<void> {
    if (this.panel) {
      this.panel.reveal();
      return;
    }

    if (!this.auditLogPath) {
      vscode.window.showWarningMessage(
        'Audit log not found. Server may not have run yet.',
        'Show Server Logs'
      ).then(choice => {
        if (choice === 'Show Server Logs') {
          this.mcpClient.getOutputChannel().show();
        }
      });
      return;
    }

    this.panel = vscode.window.createWebviewPanel(
      'mcpAuditLog',
      'MCP Audit Log',
      vscode.ViewColumn.Two,
      {
        enableScripts: true,
        retainContextWhenHidden: true
      }
    );

    this.panel.webview.html = this.getWebviewContent();

    // Handle messages from webview
    this.panel.webview.onDidReceiveMessage(async message => {
      if (message.command === 'refresh') {
        await this.updateLogs();
      } else if (message.command === 'export') {
        await this.exportLogs();
      } else if (message.command === 'filter') {
        await this.updateLogs(message.filter);
      }
    });

    this.panel.onDidDispose(() => {
      this.panel = undefined;
    });

    // Initial load
    await this.updateLogs();
  }

  private async updateLogs(filter?: {
    kernelId?: string;
    eventType?: string;
    timeRange?: { start: string; end: string };
  }): Promise<void> {
    if (!this.panel || !this.auditLogPath) return;

    try {
      const content = fs.readFileSync(this.auditLogPath, 'utf-8');
      const lines = content.split('\\n').filter(l => l.trim());
      
      // Parse log entries
      let entries = lines.map(line => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      }).filter(e => e !== null);

      // Apply filters
      if (filter) {
        if (filter.kernelId) {
          entries = entries.filter(e => e.kernel_id === filter.kernelId);
        }
        if (filter.eventType) {
          entries = entries.filter(e => e.event === filter.eventType);
        }
        if (filter.timeRange) {
          const start = new Date(filter.timeRange.start).getTime();
          const end = new Date(filter.timeRange.end).getTime();
          entries = entries.filter(e => {
            const timestamp = new Date(e.timestamp).getTime();
            return timestamp >= start && timestamp <= end;
          });
        }
      }

      // Take last 1000 entries
      entries = entries.slice(-1000);

      // Send to webview
      this.panel.webview.postMessage({ 
        type: 'update', 
        entries: entries.reverse() // Most recent first
      });
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to load audit log: ${error}`);
    }
  }

  private async exportLogs(): Promise<void> {
    if (!this.auditLogPath) return;

    const uri = await vscode.window.showSaveDialog({
      defaultUri: vscode.Uri.file('mcp-audit-export.csv'),
      filters: {
        'CSV Files': ['csv'],
        'All Files': ['*']
      }
    });

    if (!uri) return;

    try {
      const content = fs.readFileSync(this.auditLogPath, 'utf-8');
      const lines = content.split('\\n').filter(l => l.trim());
      
      const entries = lines.map(line => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      }).filter(e => e !== null);

      // Convert to CSV
      const headers = ['timestamp', 'event', 'kernel_id', 'user', 'details'];
      const csv = [
        headers.join(','),
        ...entries.map(e => {
          return [
            e.timestamp || '',
            e.event || '',
            e.kernel_id || '',
            e.user || '',
            JSON.stringify(e.details || {}).replace(/"/g, '""')
          ].map(v => `"${v}"`).join(',');
        })
      ].join('\\n');

      fs.writeFileSync(uri.fsPath, csv, 'utf-8');
      vscode.window.showInformationMessage(`Audit log exported to ${uri.fsPath}`);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to export audit log: ${error}`);
    }
  }

  private getWebviewContent(): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Audit Log</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            color: var(--vscode-foreground);
            background-color: var(--vscode-editor-background);
            padding: 20px;
            margin: 0;
        }
        
        .controls {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            padding: 10px;
            background: var(--vscode-editor-background);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 4px;
        }
        
        .controls input, .controls select {
            background: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            padding: 6px 10px;
            border-radius: 4px;
        }
        
        button {
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
        }
        
        button:hover {
            background-color: var(--vscode-button-hoverBackground);
        }
        
        .log-table {
            width: 100%;
            border-collapse: collapse;
            background: var(--vscode-editor-background);
        }
        
        .log-table th {
            background: var(--vscode-editor-background);
            color: var(--vscode-foreground);
            text-align: left;
            padding: 10px;
            border-bottom: 2px solid var(--vscode-panel-border);
            position: sticky;
            top: 0;
        }
        
        .log-table td {
            padding: 8px 10px;
            border-bottom: 1px solid var(--vscode-panel-border);
            font-size: 13px;
        }
        
        .log-table tr:hover {
            background: var(--vscode-list-hoverBackground);
        }
        
        .event-security {
            color: #f44336;
            font-weight: bold;
        }
        
        .event-kernel {
            color: #4caf50;
        }
        
        .event-execution {
            color: #2196f3;
        }
        
        .timestamp {
            color: var(--vscode-descriptionForeground);
            font-size: 12px;
        }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: var(--vscode-descriptionForeground);
        }
    </style>
</head>
<body>
    <div class="controls">
        <input type="text" id="kernelFilter" placeholder="Filter by Kernel ID">
        <select id="eventFilter">
            <option value="">All Events</option>
            <option value="kernel_start">Kernel Start</option>
            <option value="kernel_stop">Kernel Stop</option>
            <option value="execution">Execution</option>
            <option value="secret_detected">Secret Detected</option>
            <option value="package_install">Package Install</option>
        </select>
        <button onclick="applyFilter()">Filter</button>
        <button onclick="refresh()">Refresh</button>
        <button onclick="exportLogs()">Export CSV</button>
    </div>
    
    <div id="logContainer">
        <div class="empty-state">Loading audit logs...</div>
    </div>
    
    <script>
        const vscode = acquireVsCodeApi();
        let entries = [];
        
        window.addEventListener('message', event => {
            const message = event.data;
            
            if (message.type === 'update') {
                entries = message.entries;
                renderLogs();
            }
        });
        
        function renderLogs() {
            const container = document.getElementById('logContainer');
            
            if (entries.length === 0) {
                container.innerHTML = '<div class="empty-state">No audit log entries found</div>';
                return;
            }
            
            const table = document.createElement('table');
            table.className = 'log-table';
            table.innerHTML = \`
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Event</th>
                        <th>Kernel ID</th>
                        <th>Details</th>
                    </tr>
                </thead>
                <tbody></tbody>
            \`;
            
            const tbody = table.querySelector('tbody');
            entries.forEach(entry => {
                const row = document.createElement('tr');
                
                const eventClass = entry.event.includes('secret') ? 'event-security' :
                                  entry.event.includes('kernel') ? 'event-kernel' :
                                  'event-execution';
                
                row.innerHTML = \`
                    <td class="timestamp">\${new Date(entry.timestamp).toLocaleString()}</td>
                    <td class="\${eventClass}">\${entry.event}</td>
                    <td>\${entry.kernel_id || '—'}</td>
                    <td>\${JSON.stringify(entry.details || {})}</td>
                \`;
                
                tbody.appendChild(row);
            });
            
            container.innerHTML = '';
            container.appendChild(table);
        }
        
        function applyFilter() {
            const kernelId = document.getElementById('kernelFilter').value;
            const eventType = document.getElementById('eventFilter').value;
            
            vscode.postMessage({
                command: 'filter',
                filter: {
                    kernelId: kernelId || undefined,
                    eventType: eventType || undefined
                }
            });
        }
        
        function refresh() {
            vscode.postMessage({ command: 'refresh' });
        }
        
        function exportLogs() {
            vscode.postMessage({ command: 'export' });
        }
    </script>
</body>
</html>\`;
  }

  public dispose(): void {
    if (this.panel) {
      this.panel.dispose();
    }
  }
}
