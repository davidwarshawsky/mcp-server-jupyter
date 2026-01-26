import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as cp from 'child_process';

/**
 * Spawns the MCP server and configures the extension to connect to it.
 * Returns the server process for cleanup in suiteTeardown.
 */
export async function spawnTestServer(): Promise<{ proc: any; port: number }> {
    const config = vscode.workspace.getConfiguration('mcp-jupyter');
    const serverPath = path.resolve(__dirname, '../../../../tools/mcp-server-jupyter');
    const rootDir = path.resolve(__dirname, '../../../../');
    const venvPython = process.platform === 'win32'
        ? path.join(rootDir, '.venv', 'Scripts', 'python.exe')
        : path.join(rootDir, '.venv', 'bin', 'python');

    // Configure Server Path
    await config.update('serverPath', serverPath, vscode.ConfigurationTarget.Global);

    // Configure Python Path
    if (fs.existsSync(venvPython)) {
        console.log(`[TestHelper] Using .venv Python: ${venvPython}`);
        await config.update('pythonPath', venvPython, vscode.ConfigurationTarget.Global);

        // Check if mcp is installed
        const res = cp.spawnSync(venvPython, ['-c', "import mcp; import src.main; print('OK')"], { cwd: serverPath, encoding: 'utf8' });
        if (res.status !== 0) {
            console.log('[TestHelper] Installing mcp into .venv...');
            cp.spawnSync(venvPython, ['-m', 'pip', 'install', serverPath], { cwd: serverPath, stdio: 'inherit' });
        }
    } else {
        console.log('[TestHelper] .venv not found, falling back to python3');
        await config.update('pythonPath', 'python3', vscode.ConfigurationTarget.Global);
    }

    // Spawn the server
    console.log(`[TestHelper] Spawning server: ${venvPython} -m src.main --transport websocket --port 0 --idle-timeout 600`);
    console.log(`[TestHelper] CWD: ${serverPath}`);

    const serverSpawn = cp.spawn(venvPython, ['-m', 'src.main', '--transport', 'websocket', '--port', '0', '--idle-timeout', '600'], { cwd: serverPath });

    // Collect all output for diagnostics
    let allStdout = '';
    let allStderr = '';
    serverSpawn.stdout?.on('data', (data: any) => {
        const txt = data.toString();
        allStdout += txt;
        console.log(`[Server stdout] ${txt.trim()}`);
    });

    const assignedPort = await new Promise<number>((resolve, reject) => {
        const timeout = setTimeout(() => {
            console.log('[TestHelper] TIMEOUT - Server did not print port');
            console.log('[TestHelper] Captured stderr:', allStderr);
            console.log('[TestHelper] Captured stdout:', allStdout);
            reject(new Error('Timed out waiting for server port'));
        }, 10000);

        serverSpawn.stderr?.on('data', (data: any) => {
            const txt = data.toString();
            allStderr += txt;
            console.log(`[Server stderr] ${txt.trim()}`);
            const m = txt.match(/\[MCP_PORT\]:\s*(\d+)/);
            if (m) {
                clearTimeout(timeout);
                resolve(parseInt(m[1], 10));
            }
        });
        serverSpawn.on('error', (err: any) => {
            console.log(`[TestHelper] Server spawn error: ${err}`);
            clearTimeout(timeout);
            reject(err);
        });
        serverSpawn.on('exit', (code: number, signal: string) => {
            console.log(`[TestHelper] Server exited with code=${code}, signal=${signal}`);
            console.log('[TestHelper] Captured stderr:', allStderr);
            console.log('[TestHelper] Captured stdout:', allStdout);
            if (code !== null) {
                clearTimeout(timeout);
                reject(new Error(`Server exited unexpectedly with code ${code}`));
            }
        });
    });

    // Configure extension to connect to our test server
    console.log(`[TestHelper] Server started on port ${assignedPort}`);
    await config.update('serverMode', 'connect', vscode.ConfigurationTarget.Global);
    await config.update('remotePort', assignedPort, vscode.ConfigurationTarget.Global);

    // Ensure extension is active
    const extension = vscode.extensions.getExtension('warshawsky-research.mcp-agent-kernel');
    if (!extension) {
        throw new Error('Extension not found');
    }
    await extension.activate();

    // Restart the MCP client to pick up the new config
    console.log('[TestHelper] Restarting MCP client to connect to test server...');
    await vscode.commands.executeCommand('mcp-jupyter.restartServer');

    // Give it a moment to connect
    await new Promise(resolve => setTimeout(resolve, 2000));

    return { proc: serverSpawn, port: assignedPort };
}

/**
 * Cleans up the test server process
 */
export function cleanupTestServer(proc: any): void {
    if (proc) {
        try {
            proc.kill('SIGTERM');
        } catch (e) {
            console.log('[TestHelper] Error killing server:', e);
        }
    }
}
