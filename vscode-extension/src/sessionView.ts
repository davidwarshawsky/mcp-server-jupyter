/**
 * Session View Provider - Active Kernels Sidebar
 * 
 * Displays all running kernels on the MCP server, allowing users to:
 * 1. See "ghost" sessions (renamed notebooks still running)
 * 2. Attach current notebook to an existing kernel (migrate session)
 * 3. Identify which kernel is providing variables/outputs
 * 
 * This closes the gap between backend durability and frontend transparency.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import { McpClient } from './mcpClient';

export class SessionViewProvider implements vscode.TreeDataProvider<SessionItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<
    SessionItem | undefined | null | void
  >();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
  
  private sessions: SessionItem[] = [];
  private autoRefresh: NodeJS.Timeout | undefined;

  constructor(private mcpClient: McpClient) {
    // Refresh every 5 seconds to show new/removed kernels
    this.autoRefresh = setInterval(() => this.refresh(), 5000);
  }

  /**
   * Trigger a refresh of the tree view
   */
  public refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  /**
   * Get tree item for a session
   */
  getTreeItem(element: SessionItem): vscode.TreeItem {
    return element;
  }

  /**
   * Get children (kernel list)
   */
  async getChildren(element?: SessionItem): Promise<SessionItem[]> {
    if (element) {
      return [];
    }

    try {
      // Call the new server tool
      const result = await this.mcpClient.callTool('list_all_sessions', {});
      
      // Parse response
      const responseText = result.content[0].text;
      const sessions = JSON.parse(responseText);
      
      // Build tree items
      this.sessions = sessions.map(
        (s: any) =>
          new SessionItem(
            path.basename(s.notebook_path),
            s.notebook_path,
            s.pid,
            s.start_time,
            s.kernel_id,
            s.status
          )
      );
      
      return this.sessions;
    } catch (e) {
      vscode.window.showErrorMessage(
        `Failed to fetch active kernels: ${e}`
      );
      return [];
    }
  }

  /**
   * Cleanup on extension deactivation
   */
  public dispose() {
    if (this.autoRefresh) {
      clearInterval(this.autoRefresh);
    }
    this._onDidChangeTreeData.dispose();
  }
}

/**
 * Represents a running kernel session in the tree view
 */
export class SessionItem extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly fullPath: string,
    public readonly pid: number | null,
    public readonly startTime: string,
    public readonly kernelId: string,
    public readonly status: string
  ) {
    super(label, vscode.TreeItemCollapsibleState.None);
    
    // Set description (shown on the right)
    this.description = pid ? `PID: ${pid}` : 'PID: unknown';
    
    // Set tooltip (shown on hover)
    const startTimeStr = new Date(startTime).toLocaleString();
    this.tooltip = `${fullPath}\nStarted: ${startTimeStr}\nKernel ID: ${kernelId}`;
    
    // Identifies this as a session item for context menus
    this.contextValue = 'mcpSession';
    
    // Use server icon
    this.iconPath = new vscode.ThemeIcon('server-process');
  }
}
