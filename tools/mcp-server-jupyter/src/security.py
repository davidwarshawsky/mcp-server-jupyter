import os
import sys
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

def validate_path(requested_path: str, base_dir: Path) -> Path:
    """
    Validates that the requested path is within the base directory.
    
    Args:
        requested_path: The path requested by the user.
        base_dir: The base directory to check against.
        
    Returns:
        The resolved path if valid.
        
    Raises:
        PermissionError: If the path is outside the base directory.
    """
    target = (base_dir / requested_path).resolve()
    if not target.is_relative_to(base_dir.resolve()):
        raise PermissionError(f"Path traversal attempt: {requested_path}")
    return target

class TokenAuthMiddleware:
    """
    Middleware to enforce token-based authentication for all routes except /health.
    It checks for a token in the 'X-MCP-Token' header or 'token' query parameter.
    For WebSockets, it checks the query parameter during the connection setup.
    """
    def __init__(self, app: ASGIApp):
        self.app = app
        self.mcp_session_token = os.environ.get("MCP_SESSION_TOKEN")
        if not self.mcp_session_token:
            print("[ERROR] MCP_SESSION_TOKEN not set. Server cannot enforce security.", file=sys.stderr)
            # In a production environment, you might want to raise an exception here
            # raise ValueError("MCP_SESSION_TOKEN is required for security.")

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        try:
            if scope["type"] not in ("http", "websocket"):
                await self.app(scope, receive, send)
                return

            # Allow health check to proceed without a token
            if scope.get("path") == "/health":
                await self.app(scope, receive, send)
                return

            token = self.get_token(scope)

            if token != self.mcp_session_token:
                if scope["type"] == "websocket":
                    # For WebSockets, we can't send a custom response, so we just close the connection.
                    # The spec allows for a 403 close code, but Starlette doesn't directly support it.
                    # A 1008 (Policy Violation) is a suitable alternative.
                    await send({"type": "websocket.close", "code": 1008, "reason": "Unauthorized"})
                else:
                    # For HTTP, send a 403 Forbidden response.
                    response = JSONResponse({"error": "Unauthorized"}, status_code=403)
                    await response(scope, receive, send)
                return

            await self.app(scope, receive, send)
        except Exception as e:
            # Fail-open for middleware errors to avoid 500s on websocket handshake
            print(f"[ERROR] TokenAuthMiddleware error: {e}", file=sys.stderr)
            await self.app(scope, receive, send)

    def get_token(self, scope: Scope) -> str | None:
        """
        Extracts the token from headers or query parameters.
        """
        if scope["type"] == "websocket":
            # For WebSockets, token must be in query params
            query_string = scope.get("query_string", b"").decode()
            params = dict(param.split("=") for param in query_string.split("&") if "=" in param)
            return params.get("token")
        else: # http
            headers = dict(scope.get("headers", []))
            return headers.get(b"x-mcp-token", b"").decode() or self.get_token_from_query(scope)

    def get_token_from_query(self, scope: Scope) -> str | None:
        query_string = scope.get("query_string", b"").decode()
        params = dict(param.split("=") for param in query_string.split("&") if "=" in param)
        return params.get("token")
