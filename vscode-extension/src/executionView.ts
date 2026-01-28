import * as vscode from 'vscode';
import * as path from 'path';
import { MCPClient } from './mcpClient';

/**
 * Week 4: Real-Time Execution View
 * Shows active cell executions with progress and resource usage
 */

interface ActiveExecution {
  taskId: string;
  notebookPath: string;
  cellIndex: number;
  startTime: number;
  endTime?: number;
  status: 'running' | 'completed' | 'error';
  output?: string;
}

interface StatusUpdateParams {
    exec_id?: string;
    task_id?: string;
    status: 'completed' | 'error' | 'cancelled';
}

interface ExecutingUpdateParams {
    exec_id?: string;
    task_id?: string;
    notebook_path: string;
    cell_index: number;
}

export class ExecutionViewProvider implements vscode.TreeDataProvider<ExecutionTreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<ExecutionTreeItem | undefined | null>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private activeExecutions = new Map<string, ActiveExecution>();
  private completedExecutions: ActiveExecution[] = [];
  private updateInterval: NodeJS.Timeout | undefined;

  constructor(private mcpClient: MCPClient) {
    // Subscribe to notebook status notifications
    mcpClient.onNotification(notification => {
      if (notification.method === 'notebook/status') {
        this.handleStatusUpdate(notification.params);
      } else if (notification.method === 'notebook/executing') {
        this.handleExecutingUpdate(notification.params);
      }
    });

    // Update view every 2 seconds
    this.updateInterval = setInterval(() => {
      this.refresh();
    }, 2000);
  }

  private handleStatusUpdate(params: StatusUpdateParams): void {
    const taskId = params.exec_id || params.task_id;
    if (!taskId) return;
    
    const status = params.status;

    if (status === 'completed' || status === 'error' || status === 'cancelled') {
      const execution = this.activeExecutions.get(taskId);
      if (execution) {
        execution.status = status === 'error' ? 'error' : 'completed';
        execution.endTime = Date.now();
        this.completedExecutions.push(execution);
        this.activeExecutions.delete(taskId);
        
        // Keep only last 50 completed
        if (this.completedExecutions.length > 50) {
          this.completedExecutions.shift();
        }
        
        this.refresh();
      }
    }
  }

  private handleExecutingUpdate(params: ExecutingUpdateParams): void {
    const taskId = params.exec_id || params.task_id;
    if (!taskId) return;
    
    const notebookPath = params.notebook_path;
    const cellIndex = params.cell_index;

    if (!this.activeExecutions.has(taskId)) {
      this.activeExecutions.set(taskId, {
        taskId,
        notebookPath,
        cellIndex,
        startTime: Date.now(),
        status: 'running'
      });
      this.refresh();
    }
  }

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: ExecutionTreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: ExecutionTreeItem): ExecutionTreeItem[] {
    if (!element) {
      // Root level: show categories
      return [
        new ExecutionTreeItem('Active Executions', vscode.TreeItemCollapsibleState.Expanded, 'category', this.activeExecutions.size),
        new ExecutionTreeItem('Completed', vscode.TreeItemCollapsibleState.Collapsed, 'category', this.completedExecutions.length)
      ];
    }

    if (element.contextValue === 'category') {
      if (element.label === 'Active Executions') {
        return Array.from(this.activeExecutions.values()).map(exec => {
          const elapsed = Math.floor((Date.now() - exec.startTime) / 1000);
          const label = `Cell ${exec.cellIndex + 1} (${elapsed}s)`;
          const item = new ExecutionTreeItem(label, vscode.TreeItemCollapsibleState.None, 'execution');
          item.description = path.basename(exec.notebookPath);
          item.iconPath = new vscode.ThemeIcon('loading~spin');
          item.tooltip = `Notebook: ${exec.notebookPath}\nCell: ${exec.cellIndex + 1}\nElapsed: ${elapsed}s`;
          return item;
        });
      } else if (element.label === 'Completed') {
        return this.completedExecutions.slice(-10).reverse().map(exec => {
          const duration = exec.endTime ? Math.floor((exec.endTime - exec.startTime) / 1000) : 0;
          const label = `Cell ${exec.cellIndex + 1} (${duration}s)`;
          const item = new ExecutionTreeItem(label, vscode.TreeItemCollapsibleState.None, 'execution');
          item.description = path.basename(exec.notebookPath);
          item.iconPath = exec.status === 'error' 
            ? new vscode.ThemeIcon('error', new vscode.ThemeColor('errorForeground'))
            : new vscode.ThemeIcon('pass', new vscode.ThemeColor('testing.iconPassed'));
          item.tooltip = `Notebook: ${exec.notebookPath}\nCell: ${exec.cellIndex + 1}\nDuration: ${duration}s`;
          return item;
        });
      }
    }

    return [];
  }

  dispose(): void {
    if (this.updateInterval) {
      clearInterval(this.updateInterval);
    }
  }
}

class ExecutionTreeItem extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly contextValue: string,
    public readonly count?: number
  ) {
    super(label, collapsibleState);

    if (count !== undefined && contextValue === 'category') {
      this.description = `${count}`;
    }
  }
}
