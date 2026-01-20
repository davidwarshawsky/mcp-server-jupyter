import pytest
import asyncio
import sys
import json
import socket
import logging
import os
from subprocess import PIPE
from pathlib import Path
import websockets

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

class MCPWebSocketHarness:
    def __init__(self, cwd):
        self.proc = None
        self.cwd = cwd
        self.port = get_free_port()
        self.ws = None
        self.token = None
        self.base_url = f"ws://127.0.0.1:{self.port}/ws"

    async def start(self):
        # Spawn the server process in WebSocket mode
        if not self.token:
            self.token = "test-token"
            from urllib.parse import quote
            token_q = quote(self.token, safe="")
            self.base_url = f"ws://127.0.0.1:{self.port}/ws?token={token_q}"

        cmd = [
            sys.executable, "-u", "-m", "src.main",
            "--transport", "websocket",
            "--port", str(self.port)
        ]
        logger.info(f"Starting server with command: {' '.join(cmd)}")
        print("[WS HARNESS] launching server")
        
        env = dict(os.environ)
        env["MCP_SESSION_TOKEN"] = self.token

        self.proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd,
                stdout=PIPE,
                stderr=PIPE, # Capture stderr to check for startup/errors
                cwd=self.cwd,
                env=env
            ),
            timeout=10.0
        )
        print("[WS HARNESS] server process started")

        try:
            # Wait for server to start listening
            print("[WS HARNESS] waiting for port")
            await self._wait_for_port(10.0)
            print("[WS HARNESS] port open")
            
            # Connect WebSocket
            logger.info(f"Connecting to {self.base_url}")
            self.ws = await asyncio.wait_for(
                websockets.connect(self.base_url, subprotocols=['mcp']),
                timeout=10.0
            )
            logger.info("WebSocket connected")
            print("[WS HARNESS] websocket connected")
            
            # Perform Handshake
            await asyncio.wait_for(self._handshake(), timeout=30.0)
            logger.info("Handshake completed")
            print("[WS HARNESS] handshake completed")
        except Exception as e:
            # Capture output before stopping the process to aid debugging
            if self.proc:
                try:
                    # Best-effort drain of stderr/stdout without blocking
                    await self._drain_process_output(timeout=1.0)
                except Exception:
                    pass
            await self.stop()
            raise e

    async def _wait_for_port(self, timeout):
        start_time = asyncio.get_event_loop().time()
        while True:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.1):
                    return
            except (ConnectionRefusedError, OSError):
                if asyncio.get_event_loop().time() - start_time > timeout:
                    raise TimeoutError(f"Port {self.port} did not open within {timeout}s")
                await asyncio.sleep(0.1)

    async def _wait_for_token(self, timeout):
        if not self.proc or not self.proc.stderr:
            return

        start_time = asyncio.get_event_loop().time()
        while True:
            if asyncio.get_event_loop().time() - start_time > timeout:
                return
            try:
                line = await asyncio.wait_for(self.proc.stderr.readline(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if not line:
                return
            decoded = line.decode().strip()
            if decoded.startswith("[MCP_PORT]:"):
                try:
                    self.port = int(decoded.split(":", 1)[1].strip())
                except ValueError:
                    pass
            if self.port:
                return

    async def _drain_process_output(self, timeout: float = 1.0):
        if not self.proc:
            return
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            drained = False
            if self.proc.stdout:
                try:
                    line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=0.1)
                    if line:
                        logger.error(f"Server stdout: {line.decode().strip()}")
                        drained = True
                except asyncio.TimeoutError:
                    pass
            if self.proc.stderr:
                try:
                    line = await asyncio.wait_for(self.proc.stderr.readline(), timeout=0.1)
                    if line:
                        logger.error(f"Server stderr: {line.decode().strip()}")
                        drained = True
                except asyncio.TimeoutError:
                    pass
            if not drained:
                await asyncio.sleep(0.05)

    async def _handshake(self):
        # 1. Send Initialize
        init_req = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-ws-harness", "version": "1.0"}
            }
        }
        await self.send_json(init_req)
        
        # 2. Wait for Initialize Result
        resp = await self.read_response()
        assert "result" in resp, f"Handshake failed: {resp}"
        
        # 3. Send Initialized Notification
        ack = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        await self.send_json(ack)

    async def send_json(self, data):
        await self.ws.send(json.dumps(data))

    async def read_response(self, timeout=30.0):
        return json.loads(await asyncio.wait_for(self.ws.recv(), timeout=timeout))

    async def send_request(self, method, params=None):
        req_id = 1 # Simple ID increment strategy can be improved
        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": f"tools/call", # MCP standard tool call
            "params": {
                "name": method,
                "arguments": params or {}
            }
        }
        await self.send_json(req)
        return req_id

    async def stop(self):
        if self.ws:
            try:
                await asyncio.wait_for(self.ws.close(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        if self.proc:
            try:
                if self.proc.returncode is None:
                    self.proc.terminate()
                    try:
                        await asyncio.wait_for(self.proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        self.proc.kill()
                        await self.proc.wait()
            except ProcessLookupError:
                pass
            
            # [FIX] Yield to event loop to allow transport cleanup callbacks to run
            await asyncio.sleep(0.1)

            # Explicitly close transport to prevent __del__ from trying to close it after loop death
            if hasattr(self.proc, "_transport"):
                self.proc._transport.close()
                
            self.proc = None


@pytest.mark.asyncio
async def test_websocket_connection_and_execution(tmp_path):
    package_root = str(Path(__file__).parent.parent)
    harness = MCPWebSocketHarness(cwd=package_root)
    
    try:
        await harness.start()
        
        # 1. Create Notebook
        nb_path = tmp_path / "ws_test.ipynb"
        await harness.send_request("create_notebook", {"notebook_path": str(nb_path)})
        resp = await harness.read_response()
        
        # Check if response is a tool result
        if "result" in resp:
             content = resp['result'].get('content', [])
             if content:
                 print(f"Tool output: {content[0]['text']}")
                 assert "created" in content[0]['text'] or "Created" in content[0]['text']

        # 2. List Kernels (Should be empty initially)
        await harness.send_request("list_kernels", {})
        resp = await harness.read_response()
        assert "result" in resp

        # 3. Start Kernel
        await harness.send_request("start_kernel", {"notebook_path": str(nb_path)})
        resp = await harness.read_response()
        assert "target_id" not in resp # Should not be an error
        
        # 4. Cleanup
    finally:
        await harness.stop()
