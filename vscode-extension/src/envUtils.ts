/**
 * Environment utilities for MCP Jupyter extension.
 * 
 * Handles proxy settings and environment variable inheritance
 * to support corporate environments (Zscaler, Bluecoat, etc.)
 */
import * as vscode from 'vscode';

/**
 * Proxy-related environment variables that should be inherited.
 */
const PROXY_ENV_VARS = [
  // Standard proxy settings
  'HTTP_PROXY',
  'HTTPS_PROXY',
  'NO_PROXY',
  'http_proxy',
  'https_proxy',
  'no_proxy',
  
  // SSL/TLS certificate settings
  'SSL_CERT_FILE',
  'SSL_CERT_DIR',
  'REQUESTS_CA_BUNDLE',
  'CURL_CA_BUNDLE',
  'NODE_EXTRA_CA_CERTS',
  
  // pip-specific settings
  'PIP_CERT',
  'PIP_INDEX_URL',
  'PIP_TRUSTED_HOST',
  
  // Git settings (for git-based pip installs)
  'GIT_SSL_CAINFO',
  'GIT_SSL_NO_VERIFY',
];

/**
 * Get environment variables with proxy settings properly inherited.
 * 
 * This ensures pip/Python can work behind corporate proxies
 * (Zscaler, Bluecoat, etc.) by:
 * 1. Inheriting all proxy-related env vars from process.env
 * 2. Respecting VS Code's http.proxy setting
 * 3. Merging with any custom env vars provided
 * 
 * @param customEnv - Additional environment variables to merge
 * @returns Complete environment object for spawn()
 */
export function getProxyAwareEnv(customEnv: Record<string, string> = {}): Record<string, string> {
  const env: Record<string, string> = {};
  
  // Start with full process.env (critical for PATH, etc.)
  Object.assign(env, process.env);
  
  // Ensure proxy-related variables are definitely included
  for (const key of PROXY_ENV_VARS) {
    if (process.env[key]) {
      env[key] = process.env[key] as string;
    }
  }
  
  // Check VS Code's http.proxy setting
  const httpConfig = vscode.workspace.getConfiguration('http');
  const vsCodeProxy = httpConfig.get<string>('proxy');
  
  if (vsCodeProxy) {
    // VS Code has a proxy configured - use it if not already set
    if (!env['HTTP_PROXY'] && !env['http_proxy']) {
      env['HTTP_PROXY'] = vsCodeProxy;
      env['http_proxy'] = vsCodeProxy;
    }
    if (!env['HTTPS_PROXY'] && !env['https_proxy']) {
      env['HTTPS_PROXY'] = vsCodeProxy;
      env['https_proxy'] = vsCodeProxy;
    }
  }
  
  // Check VS Code's proxy strict SSL setting
  const proxyStrictSSL = httpConfig.get<boolean>('proxyStrictSSL');
  if (proxyStrictSSL === false) {
    // User has disabled strict SSL (common for self-signed corporate certs)
    env['NODE_TLS_REJECT_UNAUTHORIZED'] = '0';
    // Note: This is insecure but sometimes required in corporate environments
  }
  
  // Merge custom env vars (these take precedence)
  Object.assign(env, customEnv);
  
  return env;
}

/**
 * Get spawn options with proper environment inheritance.
 * 
 * @param cwd - Working directory for the spawned process
 * @param stdio - stdio configuration (default: pipe for stdin/stdout/stderr)
 * @returns SpawnOptions object ready for child_process.spawn()
 */
export function getProxyAwareSpawnOptions(
  cwd?: string,
  stdio: 'pipe' | 'inherit' | 'ignore' | Array<'pipe' | 'inherit' | 'ignore' | 'ipc'> = ['pipe', 'pipe', 'pipe']
): { cwd?: string; env: Record<string, string>; stdio: typeof stdio } {
  return {
    ...(cwd && { cwd }),
    env: getProxyAwareEnv(),
    stdio,
  };
}

/**
 * Log proxy configuration for debugging.
 * 
 * @param outputChannel - VS Code output channel to log to
 */
export function logProxyConfig(outputChannel: vscode.OutputChannel): void {
  outputChannel.appendLine('=== Proxy Configuration ===');
  
  for (const key of PROXY_ENV_VARS) {
    const value = process.env[key];
    if (value) {
      // Mask sensitive parts of URLs (passwords)
      const masked = value.replace(/(:\/\/[^:]+:)[^@]+@/, '$1****@');
      outputChannel.appendLine(`  ${key}: ${masked}`);
    }
  }
  
  const httpConfig = vscode.workspace.getConfiguration('http');
  const vsCodeProxy = httpConfig.get<string>('proxy');
  if (vsCodeProxy) {
    const masked = vsCodeProxy.replace(/(:\/\/[^:]+:)[^@]+@/, '$1****@');
    outputChannel.appendLine(`  VS Code http.proxy: ${masked}`);
  }
  
  outputChannel.appendLine('===========================');
}
