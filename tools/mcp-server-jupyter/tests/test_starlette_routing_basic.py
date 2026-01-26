import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import WebSocketRoute, Route
from starlette.websockets import WebSocket
from starlette.testclient import TestClient


async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("Hello!")
    await websocket.close()


async def http_endpoint(request):
    return PlainTextResponse("HTTP endpoint works!")


@pytest.mark.optional
def test_starlette_http_and_ws_routes():
    app = Starlette(
        routes=[Route("/", http_endpoint), WebSocketRoute("/ws", ws_endpoint)]
    )

    with TestClient(app) as client:
        # HTTP
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.text == "HTTP endpoint works!"

        # WS
        with client.websocket_connect("/ws") as ws:
            msg = ws.receive_text()
            assert msg == "Hello!"
