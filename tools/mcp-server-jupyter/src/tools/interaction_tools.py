"""
Interaction Tools - user interaction helpers (secret requests, input prompts).

Provides: request_secret to safely ask human for a secret and inject it into the kernel env.
"""

import json


def register_interaction_tools(mcp, session_manager):
    """Register interaction tools with MCP."""

    @mcp.tool()
    async def request_secret(
        notebook_path: str, key_name: str, reason: str = ""
    ) -> str:
        """
        Request a secret (API Key, Password) from the human user.

        The value is injected directly into os.environ in the kernel session via the
        existing submit_input/secret injection flow handled by the client extension.
        Returns a confirmation message to the caller.
        """
        # Build notification payload the VS Code extension understands
        payload = {
            "notebook_path": notebook_path,
            "prompt": f"Agent requests secret '{key_name}' for: {reason}",
            "password": True,
            "secret_key": key_name,
        }

        # Use session_manager helper to send notification (broadcasts to connected clients)
        try:
            await session_manager._send_notification("notebook/input_request", payload)
        except Exception:
            # Best-effort: fall back to server-level notification if available
            try:
                if (
                    hasattr(session_manager, "mcp_server")
                    and session_manager.mcp_server
                ):
                    await session_manager.mcp_server.send_notification(
                        {"method": "notebook/input_request", "params": payload}
                    )
            except Exception:
                pass

        return json.dumps({"status": "requested", "key": key_name})
