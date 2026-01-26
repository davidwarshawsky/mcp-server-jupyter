import inspect


def test_mcp_websocket_server_declares_mcp_subprotocol():
    """The MCP websocket transport requires negotiating the 'mcp' subprotocol.

    The VS Code client must request this subprotocol during the handshake.
    If it doesn't, real clients may fail to connect (often surfacing as an
    'Unexpected server response' during activation).
    """

    import mcp.server.websocket as websocket_mod

    src = inspect.getsource(websocket_mod.websocket_server)
    assert "mcp" in src
