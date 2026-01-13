import * as vscode from 'vscode';
import { McpClient } from './mcpClient';

interface VariableInfo {
  name: string;
  type: string;
  size: string;
}

export class VariableDashboardProvider implements vscode.TreeDataProvider<VariableItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<VariableItem | undefined | null | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
  
  private variables: VariableInfo[] = [];
  private currentNotebook?: string;
  private pollInterval?: NodeJS.Timeout;
  private isPolling = false;
  private suspended = false;

  constructor(private mcpClient: McpClient) {}

  /**
   * Start polling for variables when kernel is idle
   */
  startPolling(notebookPath: string): void {
    this.currentNotebook = notebookPath;
    
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
    }

    // Poll every 2 seconds when kernel is idle
    this.pollInterval = setInterval(async () => {
      if (!this.isPolling && !this.suspended) {
        await this.refresh();
      }
    }, 2000);

    // Initial refresh
    this.refresh();
  }

  /**
   * Stop polling when notebook is closed or kernel stopped
   */
  stopPolling(): void {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = undefined;
    }
    this.currentNotebook = undefined;
    this.variables = [];
    this._onDidChangeTreeData.fire();
  }

  /**
   * Refresh variable list from kernel
   */
  async refresh(): Promise<void> {
    if (!this.currentNotebook || this.isPolling || this.suspended) {
      return;
    }

    try {
      this.isPolling = true;
      const result = await this.mcpClient.getVariableManifest(this.currentNotebook);
      
      if (Array.isArray(result)) {
        this.variables = result;
        this._onDidChangeTreeData.fire();
      }
    } catch (error) {
      // Silent fail - kernel might not be ready yet
      console.log('Failed to get variable manifest:', error);
    } finally {
      this.isPolling = false;
    }
  }

  /**
   * Suspend polling while kernel is busy
   */
  setBusy(busy: boolean): void {
    this.suspended = busy;
  }

  /**
   * Get tree item for display
   */
  getTreeItem(element: VariableItem): vscode.TreeItem {
    return element;
  }

  /**
   * Get children (root level = variables)
   */
  getChildren(element?: VariableItem): Thenable<VariableItem[]> {
    if (element) {
      return Promise.resolve([]);
    }

    if (this.variables.length === 0) {
      return Promise.resolve([]);
    }

    return Promise.resolve(
      this.variables.map(v => new VariableItem(v.name, v.type, v.size))
    );
  }
}

class VariableItem extends vscode.TreeItem {
  constructor(
    public readonly name: string,
    public readonly type: string,
    public readonly size: string
  ) {
    super(name, vscode.TreeItemCollapsibleState.None);
    
    this.description = `${type}`;
    this.tooltip = `${name}: ${type} (${size})`;
    
    // Use different icons based on type
    this.iconPath = new vscode.ThemeIcon(this.getIconForType(type));
    
    // Add size as context value for large objects
    this.contextValue = this.isLargeObject() ? 'largeVariable' : 'variable';
  }

  private getIconForType(type: string): string {
    const typeLower = type.toLowerCase();
    
    if (typeLower.includes('dataframe')) return 'table';
    if (typeLower.includes('list') || typeLower.includes('array')) return 'list-unordered';
    if (typeLower.includes('dict')) return 'symbol-namespace';
    if (typeLower.includes('str')) return 'symbol-string';
    if (typeLower.includes('int') || typeLower.includes('float')) return 'symbol-number';
    if (typeLower.includes('bool')) return 'symbol-boolean';
    if (typeLower.includes('function')) return 'symbol-function';
    if (typeLower.includes('class') || typeLower.includes('object')) return 'symbol-class';
    if (typeLower.includes('module')) return 'package';
    
    return 'symbol-variable';
  }

  private isLargeObject(): boolean {
    // Parse size string (e.g., "2.3 MB", "128 KB")
    const match = this.size.match(/^([\d.]+)\s*([KMG]?B)/);
    if (!match) return false;
    
    const value = parseFloat(match[1]);
    const unit = match[2];
    
    if (unit === 'MB' && value > 10) return true;
    if (unit === 'GB') return true;
    
    return false;
  }
}

/**
 * Get empty state message view
 */
export class EmptyVariableView implements vscode.TreeDataProvider<vscode.TreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<vscode.TreeItem | undefined | null | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(): Thenable<vscode.TreeItem[]> {
    const item = new vscode.TreeItem('No kernel running', vscode.TreeItemCollapsibleState.None);
    item.description = 'Execute a cell to start kernel';
    item.iconPath = new vscode.ThemeIcon('circle-outline');
    return Promise.resolve([item]);
  }
}
