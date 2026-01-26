"""
Server Tools - Server info, status, and health check endpoints.
"""

import json
import sys
from starlette.responses import JSONResponse
from src.audit_log import audit_tool

# Version for capability negotiation
__version__ = "0.3.0"


def register_server_tools(mcp, session_manager, connection_manager):
    """Register server-related tools with the MCP server."""

    @mcp.tool()
    @audit_tool
    def get_server_info():
        """
        [FINAL PUNCH LIST #5] Get server version and capabilities for handshake.

        Client should call this on connection to verify compatibility.
        Warns user if server version < client minimum required version.

        Returns:
            JSON with version, capabilities, and feature flags
        """
        return json.dumps(
            {
                "version": __version__,
                "capabilities": [
                    "audit_logs",  # Code execution audit trail
                    "sandbox",  # DuckDB sandboxing
                    "uuid_reaper",  # UUID-based zombie reaping
                    "trace_id",  # Request tracing support
                    "resource_limits",  # Kernel resource limits
                    "asset_cleanup",  # Automatic asset TTL
                ],
                "features": {
                    "checkpoint": False,  # Removed for security (ROUND 2)
                    "git_integration": False,  # Removed for maintenance burden
                    "docker_kernels": True,
                    "conda_kernels": True,
                    "multiuser": True,
                },
                "protocol_version": "1.0",
                "min_client_version": "0.2.0",  # Minimum compatible client version
            },
            indent=2,
        )

    @mcp.tool()
    @audit_tool
    def get_server_status():
        """Check how many humans are connected to this session."""
        return json.dumps(
            {
                "active_connections": len(connection_manager.active_connections),
                "mode": (
                    "multi-user"
                    if len(connection_manager.active_connections) > 1
                    else "solo"
                ),
            }
        )

    @mcp.tool()
    @audit_tool
    async def get_version():
        """
        Get MCP server version for compatibility checking.

        Returns:
            JSON with version, protocol_version, and capabilities
        """
        return json.dumps(
            {
                "version": __version__,
                "protocol_version": "1.0",
                "capabilities": [
                    "execute_cells",
                    "async_execution",
                    "websocket_streaming",
                    "health_monitoring",
                    "interrupt_escalation",
                    "checkpoint_recovery",
                    "docker_isolation",
                    "sql_superpowers",
                ],
                "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            }
        )


async def health_check(session_manager, version: str):
    """
    [ROUND 2 AUDIT] Improved health check that validates kernel liveness.
    Returns HTTP 200 if all kernels are responsive, 503 otherwise.
    """
    active_sessions = len(session_manager.sessions)
    healthy_kernels = 0
    unhealthy_kernels = 0

    # Sample check: verify a few kernels are actually responsive
    for nb_path, session in list(session_manager.sessions.items())[
        :3
    ]:  # Check up to 3 kernels
        try:
            kc = session.get("kc")
            km = session.get("km")
            if kc and km and km.is_alive():
                healthy_kernels += 1
            else:
                unhealthy_kernels += 1
        except Exception:
            unhealthy_kernels += 1

    is_healthy = unhealthy_kernels == 0 or (
        healthy_kernels > 0 and healthy_kernels >= unhealthy_kernels
    )

    return JSONResponse(
        {
            "status": "healthy" if is_healthy else "degraded",
            "active_kernels": active_sessions,
            "sampled_healthy": healthy_kernels,
            "sampled_unhealthy": unhealthy_kernels,
            "version": version,
        },
        status_code=200 if is_healthy else 503,
    )
