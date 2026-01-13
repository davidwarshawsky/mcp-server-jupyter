import pytest
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket
from starlette.testclient import TestClient


async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("Hello from test server!")
    await websocket.close()


@pytest.mark.optional
def test_minimal_websocket_route():
    app = Starlette(routes=[WebSocketRoute("/ws", websocket_endpoint)])

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_text()
            assert data == "Hello from test server!"
