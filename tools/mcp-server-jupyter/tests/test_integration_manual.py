import pytest
import asyncio
import subprocess
import sys
import os
import signal
import time
from pathlib import Path

# Path to the manual connection script
MANUAL_TEST_SCRIPT = Path(__file__).parent / "manual_connect_test.py"
# The CWD is expected to be the root of the sub-project (tools/mcp-server-jupyter)
# because pytest is run from there.
SERVER_CWD = Path(__file__).parent.parent

@pytest.mark.asyncio
async def test_manual_verification_flow():
    """
    Automates the 'manual verification' process by spawning the server 
    and then running the manual connection script against it.
    """
    server_process = None
    client_process = None

    # 1. Start the MCP Server in a subprocess
    server_port = 8123
    server_env = os.environ.copy()
    server_env["PORT"] = str(server_port)
    server_env["PYTHONPATH"] = str(SERVER_CWD)
    
    print(f"Starting server on port {server_port}...")
    server_cmd = [sys.executable, "-m", "src.main", "--transport", "websocket", "--port", str(server_port)]
    
    server_process = subprocess.Popen(
        server_cmd,
        cwd=str(SERVER_CWD),
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        # Give the server a moment to start up
        await asyncio.sleep(5) 
        
        if server_process.poll() is not None:
            stdout, stderr = server_process.communicate()
            pytest.fail(f"Server exited prematurely.\nCommand: {' '.join(server_cmd)}\nStdout: {stdout}\nStderr: {stderr}")

        print("Server process appears running. Running client script...")

        # 2. Run the manual connect script unbuffered
        client_cmd = [sys.executable, "-u", str(MANUAL_TEST_SCRIPT), "--port", str(server_port)]
        
        print(f"Running client: {' '.join(client_cmd)}")
        client_process = await asyncio.create_subprocess_exec(
            *client_cmd,
            cwd=str(SERVER_CWD),
            env=server_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # 3. Stream Output and Verify
        is_connected = False
        is_handshake = False
        captured_output = []
        
        try:
            start_time = time.time()
            while time.time() - start_time < 10: # 10s timeout
                if client_process.stdout.at_eof():
                    break
                    
                try:
                    line_bytes = await asyncio.wait_for(client_process.stdout.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                    
                if not line_bytes:
                    continue
                    
                line = line_bytes.decode().strip()
                if line:
                    print(f"[CLIENT] {line}")
                    captured_output.append(line)
                    
                    if "✅ Human connected!" in line:
                        is_connected = True
                    if "Handshake received" in line or "✅ Handshake response" in line:
                        is_handshake = True
                        break # Success!
                
        except Exception as e:
            print(f"Error reading client output: {e}")
        
        # Check standard error too just in case
        if not is_handshake:
            # Read stderr if failure
            try:
                if client_process.returncode is None:
                    client_process.kill()
                out, err = await client_process.communicate()
                if err:
                    print(f"[CLIENT STDERR]\n{err.decode()}")
            except:
                pass

        # 4. Assertions
        if not (is_connected and is_handshake):
             # Dump server logs
            server_process.terminate()
            s_out, s_err = server_process.communicate()
            print(f"--- SERVER LOGS ---\nSTDOUT: {s_out}\nSTDERR: {s_err}\n-------------------")
            
        assert is_connected, "Client failed to connect to server (Log mismatch)"
        assert is_handshake, "Client connected but failed to receive handshake (Log mismatch)"

    finally:
        if client_process and client_process.returncode is None:
            try:
                client_process.kill()
            except:
                pass
                
        if server_process and server_process.poll() is None:
            print("Terminating server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
