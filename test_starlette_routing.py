#!/usr/bin/env python3
"""Test if Starlette routing is working at all"""
import uvicorn
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute, Route
from starlette.websockets import WebSocket
from starlette.responses import PlainTextResponse

async def websocket_endpoint(websocket: WebSocket):
    print(f"🔵 WebSocket endpoint called from {websocket.client}")
    await websocket.accept()
    print("✅ WebSocket accepted")
    await websocket.send_text("Hello!")
    await websocket.close()

async def http_endpoint(request):
    return PlainTextResponse("HTTP endpoint works!")

app = Starlette(
    debug=True,
    routes=[
        Route("/", http_endpoint),
        WebSocketRoute("/ws", websocket_endpoint)
    ]
)

if __name__ == "__main__":
    print("🚀 Starting test server on port 3000...")
    print("HTTP: http://localhost:3000/")
    print("WS: ws://localhost:3000/ws")
    uvicorn.run(app, host="0.0.0.0", port=3000, log_level="debug")
