import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Week 3: Error Classification System
 * Classifies connection errors and provides actionable guidance
 */

export enum ConnectionFailureReason {
  AUTH_FAILED = 'auth',
  NETWORK_ERROR = 'network',
  SERVER_CRASH = 'crash',
  PORT_IN_USE = 'port',
  TIMEOUT = 'timeout',
  UNKNOWN = 'unknown'
}

export interface ClassifiedError {
  reason: ConnectionFailureReason;
  message: string;
  userMessage: string;
  actionableSteps: string[];
  canRetry: boolean;
}

export class ErrorClassifier {
  private telemetryLog: string;

  constructor(private context: vscode.ExtensionContext) {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (workspaceFolder) {
      const vscodeDir = path.join(workspaceFolder.uri.fsPath, '.vscode');
      this.telemetryLog = path.join(vscodeDir, 'mcp-telemetry.jsonl');
    } else {
      // Fallback to extension storage
      this.telemetryLog = path.join(context.globalStorageUri.fsPath, 'mcp-telemetry.jsonl');
    }
  }

  /**
   * Classify a connection error and provide guidance
   */
  public classify(error: Error | string): ClassifiedError {
    const errorMsg = error instanceof Error ? error.message : String(error);

    // Authentication failures
    if (this.isAuthError(errorMsg)) {
      return {
        reason: ConnectionFailureReason.AUTH_FAILED,
        message: errorMsg,
        userMessage: '🔐 Authentication failed',
        actionableSteps: [
          'Generate a new session token:',
          '  $ openssl rand -hex 32',
          'Update your VS Code settings:',
          '  "mcp-jupyter.sessionToken": "<your-token>"',
          'Or restart the server to generate a new token automatically'
        ],
        canRetry: false
      };
    }

    // Network errors (DNS, connection refused, timeout)
    if (this.isNetworkError(errorMsg)) {
      return {
        reason: ConnectionFailureReason.NETWORK_ERROR,
        message: errorMsg,
        userMessage: '🌐 Network connection failed',
        actionableSteps: [
          'Check if the server is running:',
          '  $ ps aux | grep mcp-jupyter',
          'Verify the host and port in settings',
          'Check firewall rules (port 3000 must be open)',
          'Try pinging the server host'
        ],
        canRetry: true
      };
    }

    // Port already in use
    if (this.isPortInUse(errorMsg)) {
      return {
        reason: ConnectionFailureReason.PORT_IN_USE,
        message: errorMsg,
        userMessage: '🔌 Port already in use',
        actionableSteps: [
          'Kill the existing server process:',
          '  $ lsof -ti :3000 | xargs kill -9',
          'Or configure a different port in settings:',
          '  "mcp-jupyter.port": 3001'
        ],
        canRetry: true
      };
    }

    // Server crash (process exited)
    if (this.isServerCrash(errorMsg)) {
      return {
        reason: ConnectionFailureReason.SERVER_CRASH,
        message: errorMsg,
        userMessage: '💥 Server process crashed',
        actionableSteps: [
          'Check server logs for errors:',
          '  Command: "MCP Jupyter: Show Server Logs"',
          'Common causes:',
          '  - Missing Python dependencies (pip install -e .)',
          '  - Python version mismatch (requires 3.10+)',
          '  - Corrupted virtual environment (recreate with Quick Start)'
        ],
        canRetry: true
      };
    }

    // Timeout (slow response)
    if (this.isTimeout(errorMsg)) {
      return {
        reason: ConnectionFailureReason.TIMEOUT,
        message: errorMsg,
        userMessage: '⏱️ Connection timeout',
        actionableSteps: [
          'The server is taking too long to respond',
          'Possible causes:',
          '  - Server is under heavy load',
          '  - Network latency is high',
          '  - Server is starting up (wait 10 seconds and retry)'
        ],
        canRetry: true
      };
    }

    // Unknown error
    return {
      reason: ConnectionFailureReason.UNKNOWN,
      message: errorMsg,
      userMessage: '❓ Unknown connection error',
      actionableSteps: [
        'View full error details in logs:',
        '  Command: "MCP Jupyter: Show Server Logs"',
        'Try restarting the server:',
        '  Command: "MCP Jupyter: Restart Server"',
        'Report this issue if problem persists'
      ],
      canRetry: true
    };
  }

  /**
   * Log telemetry event (privacy-preserving)
   */
  public async logTelemetry(event: {
    type: 'connection_failure' | 'connection_success' | 'reconnection';
    reason?: ConnectionFailureReason;
    retryAttempt?: number;
    duration?: number;
  }): Promise<void> {
    try {
      // Ensure directory exists
      const dir = path.dirname(this.telemetryLog);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      // Create telemetry entry (NO PII)
      const entry = {
        timestamp: new Date().toISOString(),
        event: event.type,
        reason: event.reason,
        retryAttempt: event.retryAttempt,
        duration: event.duration,
        // NO user data, paths, or identifiable information
      };

      // Append to JSONL file
      fs.appendFileSync(
        this.telemetryLog,
        JSON.stringify(entry) + '\n',
        'utf-8'
      );

      // Keep only last 1000 entries (privacy: automatic cleanup)
      await this.rotateTelemetryLog(1000);
    } catch (error) {
      // Silently fail - telemetry is not critical
      console.error('Failed to log telemetry:', error);
    }
  }

  /**
   * Get telemetry summary for diagnostics
   */
  public async getTelemetrySummary(): Promise<{
    totalFailures: number;
    failuresByReason: Record<string, number>;
    successRate: number;
    avgReconnectionTime: number;
  }> {
    try {
      if (!fs.existsSync(this.telemetryLog)) {
        return {
          totalFailures: 0,
          failuresByReason: {},
          successRate: 1.0,
          avgReconnectionTime: 0
        };
      }

      const lines = fs.readFileSync(this.telemetryLog, 'utf-8').split('\n').filter(l => l.trim());
      const events = lines.map(line => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      }).filter(e => e !== null);

      const failures = events.filter(e => e.event === 'connection_failure');
      const successes = events.filter(e => e.event === 'connection_success');
      const reconnections = events.filter(e => e.event === 'reconnection');

      const failuresByReason: Record<string, number> = {};
      failures.forEach(f => {
        const reason = f.reason || 'unknown';
        failuresByReason[reason] = (failuresByReason[reason] || 0) + 1;
      });

      const totalEvents = failures.length + successes.length;
      const successRate = totalEvents > 0 ? successes.length / totalEvents : 1.0;

      const reconnectionTimes = reconnections
        .map(r => r.duration)
        .filter(d => typeof d === 'number' && d > 0);
      const avgReconnectionTime = reconnectionTimes.length > 0
        ? reconnectionTimes.reduce((a, b) => a + b, 0) / reconnectionTimes.length
        : 0;

      return {
        totalFailures: failures.length,
        failuresByReason,
        successRate,
        avgReconnectionTime
      };
    } catch (error) {
      console.error('Failed to get telemetry summary:', error);
      return {
        totalFailures: 0,
        failuresByReason: {},
        successRate: 1.0,
        avgReconnectionTime: 0
      };
    }
  }

  /**
   * Rotate telemetry log to keep file size manageable
   */
  private async rotateTelemetryLog(maxEntries: number): Promise<void> {
    try {
      if (!fs.existsSync(this.telemetryLog)) {
        return;
      }

      const lines = fs.readFileSync(this.telemetryLog, 'utf-8').split('\n').filter(l => l.trim());
      
      if (lines.length > maxEntries) {
        // Keep only the most recent entries
        const recentLines = lines.slice(-maxEntries);
        fs.writeFileSync(this.telemetryLog, recentLines.join('\n') + '\n', 'utf-8');
      }
    } catch (error) {
      console.error('Failed to rotate telemetry log:', error);
    }
  }

  /**
   * Check if error is authentication failure
   */
  private isAuthError(msg: string): boolean {
    const authPatterns = [
      /401/i,
      /unauthorized/i,
      /authentication.*failed/i,
      /invalid.*token/i,
      /forbidden/i,
      /access.*denied/i
    ];
    return authPatterns.some(pattern => pattern.test(msg));
  }

  /**
   * Check if error is network-related
   */
  private isNetworkError(msg: string): boolean {
    const networkPatterns = [
      /ECONNREFUSED/i,
      /ENOTFOUND/i,
      /EHOSTUNREACH/i,
      /ENETUNREACH/i,
      /connection refused/i,
      /network.*unreachable/i,
      /dns.*failed/i,
      /getaddrinfo/i
    ];
    return networkPatterns.some(pattern => pattern.test(msg));
  }

  /**
   * Check if error is port conflict
   */
  private isPortInUse(msg: string): boolean {
    const portPatterns = [
      /EADDRINUSE/i,
      /port.*already.*in.*use/i,
      /address.*already.*in.*use/i
    ];
    return portPatterns.some(pattern => pattern.test(msg));
  }

  /**
   * Check if error is server crash
   */
  private isServerCrash(msg: string): boolean {
    const crashPatterns = [
      /process.*exited/i,
      /server.*crashed/i,
      /child.*process.*died/i,
      /exit.*code/i,
      /SIGTERM/i,
      /SIGKILL/i
    ];
    return crashPatterns.some(pattern => pattern.test(msg));
  }

  /**
   * Check if error is timeout
   */
  private isTimeout(msg: string): boolean {
    const timeoutPatterns = [
      /timeout/i,
      /ETIMEDOUT/i,
      /timed.*out/i,
      /no.*response/i
    ];
    return timeoutPatterns.some(pattern => pattern.test(msg));
  }

  /**
   * Show classified error to user with actionable guidance
   */
  public async showError(classified: ClassifiedError): Promise<void> {
    const message = `${classified.userMessage}\n\n${classified.actionableSteps.join('\n')}`;
    
    const actions: string[] = ['Show Logs'];
    if (classified.canRetry) {
      actions.push('Retry');
    }
    if (classified.reason === ConnectionFailureReason.SERVER_CRASH) {
      actions.push('Restart Server');
    }

    const choice = await vscode.window.showErrorMessage(message, ...actions);

    if (choice === 'Show Logs') {
      vscode.commands.executeCommand('mcp-jupyter.showServerLogs');
    } else if (choice === 'Retry') {
      vscode.commands.executeCommand('mcp-jupyter.testConnection');
    } else if (choice === 'Restart Server') {
      vscode.commands.executeCommand('mcp-jupyter.restartServer');
    }
  }
}
