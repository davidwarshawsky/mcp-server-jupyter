#!/usr/bin/env python3
"""Minimal Starlette WebSocket server to test the setup

Note: This is a manual utility script. Automated coverage exists in
tools/mcp-server-jupyter/tests/ (Starlette routing/WS). Marked skipped for pytest.
"""
import pytest
pytestmark = pytest.mark.skip("Manual script, not a pytest test. See automated tests under tools/mcp-server-jupyter/tests/.")
import uvicorn
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket

async def websocket_endpoint(websocket: WebSocket):
    print(f"Connection attempt from {websocket.client}")
    await websocket.accept()
    print("WebSocket accepted!")
    await websocket.send_text("Hello from test server!")
    await websocket.close()

app = Starlette(
    routes=[
        WebSocketRoute("/ws", websocket_endpoint)
    ]
)

if __name__ == "__main__":
    print("Starting test WebSocket server on port 3001...")
    uvicorn.run(app, host="0.0.0.0", port=3001, log_level="info")
