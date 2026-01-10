/**
 * Type definitions for MCP protocol communication
 */

export interface McpRequest {
  jsonrpc: '2.0';
  id: number;
  method: string;
  params?: {
    name: string;
    arguments: Record<string, any>;
  };
}

export interface McpResponse {
  jsonrpc: '2.0';
  id?: number | null;
  result?: any;
  method?: string; // For notifications
  params?: any;    // For notifications
  error?: {
    code: number;
    message: string;
    data?: any;
  };
}

export interface ExecutionStatus {
  status: 'queued' | 'running' | 'completed' | 'error';
  outputs?: NotebookOutput[];
  execution_count?: number;
  error?: {
    ename: string;
    evalue: string;
    traceback: string[];
  };
}

export interface NotebookOutput {
  output_type: 'stream' | 'execute_result' | 'display_data' | 'error';
  name?: string;  // for stream
  text?: string | string[];  // for stream
  data?: Record<string, any>;  // for execute_result, display_data
  metadata?: Record<string, any>;
  execution_count?: number;  // for execute_result
  ename?: string;  // for error
  evalue?: string;  // for error
  traceback?: string[];  // for error
}

export interface PythonEnvironment {
  type: 'conda' | 'venv' | 'system';
  name: string;
  path: string;
  python_version?: string;
}
