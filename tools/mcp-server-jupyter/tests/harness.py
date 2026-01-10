import asyncio
import json
import sys
import os
from subprocess import PIPE
from pathlib import Path

class MCPServerHarness:
    def __init__(self, cwd):
        self.proc = None
        self.cwd = cwd

    async def start(self):
        # Spawn the actual server process
        # We assume 'src.main' is runnable via python -m from the package root
        # stderr=None inherits stderr, allowing us to see server logs in the test runner output
        # -u forces unbuffered stdout, critical for JSON-RPC over stdio
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-m", "src.main",
            stdin=PIPE, 
            stdout=PIPE, 
            stderr=None,  
            cwd=self.cwd
        )
        # Perform MCP Handshake
        await self._handshake()

    async def _handshake(self):
        # 1. Send Initialize
        init_req = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05", # 2024-11-05 is a valid protocol string
                "capabilities": {},
                "clientInfo": {"name": "test-harness", "version": "1.0"}
            }
        }
        await self._send_json(init_req)
        
        # 2. Wait for Initialize Result
        # Timeout safety for handshake
        resp = await asyncio.wait_for(self.read_response(), timeout=5.0)
        assert "result" in resp, f"Handshake failed: {resp}"
        
        # 3. Send Initialized Notification
        ack = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        await self._send_json(ack)

    async def _send_json(self, data):
        json_data = json.dumps(data).encode() + b"\n"
        self.proc.stdin.write(json_data)
        await self.proc.stdin.drain()

    async def send_request(self, method, args):
        req = {
            "jsonrpc": "2.0",
            "id": 2, # simplified id
            "method": "tools/call", 
            "params": {
                "name": method,
                "arguments": args
            }
        }
        await self._send_json(req)

    async def read_response(self, timeout=5.0):
        # Read lines until we get a response or notification
        while True:
            try:
                # Add timeout to readline so we don't hang forever
                line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=timeout)
            except asyncio.TimeoutError:
                raise TimeoutError("Server was silent for too long while waiting for response")
            except Exception:
                 raise EOFError("Server closed connection during read")

            if not line: 
                raise EOFError("Server closed connection")
                
            try:
                # print(f"DEBUG_HARNESS: {line.decode().strip()}", file=sys.stderr)
                msg = json.loads(line.decode())
                return msg
            except json.JSONDecodeError:
                # Could be raw text or partial line
                continue

    async def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
                await self.proc.wait()
            except ProcessLookupError:
                pass
