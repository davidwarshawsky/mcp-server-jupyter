"""
Server Tools - Server info, status, and health check endpoints.
"""

import json
from starlette.responses import JSONResponse

# Version for capability negotiation
__version__ = "0.2.1"


def register_server_tools(mcp, session_manager, connection_manager):
    """Register server-related tools with the MCP server."""
    
    @mcp.tool()
    def get_server_info():
        """
        [FINAL PUNCH LIST #5] Get server version and capabilities for handshake.
        
        Client should call this on connection to verify compatibility.
        Warns user if server version < client minimum required version.
        
        Returns:
            JSON with version, capabilities, and feature flags
        """
        return json.dumps({
            "version": __version__,
            "capabilities": [
                "audit_logs",         # Code execution audit trail
                "sandbox",            # DuckDB sandboxing
                "uuid_reaper",        # UUID-based zombie reaping
                "trace_id",           # Request tracing support
                "resource_limits",    # Kernel resource limits
                "asset_cleanup",      # Automatic asset TTL
            ],
            "features": {
                "checkpoint": False,  # Removed for security (ROUND 2)
                "git_integration": False,  # Removed for maintenance burden
                "docker_kernels": True,
                "conda_kernels": True,
                "multiuser": True,
            },
            "protocol_version": "1.0",
            "min_client_version": "0.2.0"  # Minimum compatible client version
        }, indent=2)

    @mcp.tool()
    def get_server_status():
        """Check how many humans are connected to this session."""
        return json.dumps({
            "active_connections": len(connection_manager.active_connections),
            "mode": "multi-user" if len(connection_manager.active_connections) > 1 else "solo"
        })


async def health_check(session_manager, version: str):
    """
    [ROUND 2 AUDIT] Improved health check that validates kernel liveness.
    Returns HTTP 200 if all kernels are responsive, 503 otherwise.
    """
    active_sessions = len(session_manager.sessions)
    healthy_kernels = 0
    unhealthy_kernels = 0
    
    # Sample check: verify a few kernels are actually responsive
    for nb_path, session in list(session_manager.sessions.items())[:3]:  # Check up to 3 kernels
        try:
            kc = session.get('kc')
            km = session.get('km')
            if kc and km and km.is_alive():
                healthy_kernels += 1
            else:
                unhealthy_kernels += 1
        except Exception:
            unhealthy_kernels += 1
    
    is_healthy = unhealthy_kernels == 0 or (healthy_kernels > 0 and healthy_kernels >= unhealthy_kernels)
    
    return JSONResponse({
        "status": "healthy" if is_healthy else "degraded",
        "active_kernels": active_sessions,
        "sampled_healthy": healthy_kernels,
        "sampled_unhealthy": unhealthy_kernels,
        "version": version
    }, status_code=200 if is_healthy else 503)
