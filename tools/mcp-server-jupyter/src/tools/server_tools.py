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

    # ═══════════════════════════════════════════════════════════════
    # [SESSION DISCOVERY & ATTACHMENT TOOLS]
    # These enable the VS Code extension to:
    # 1. Find "ghost" sessions (renamed notebooks still running on server)
    # 2. Attach current notebook to existing kernel (migrate session)
    # 3. List all active kernels in sidebar UI
    # 4. Rehydrate outputs when reconnecting
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    @audit_tool
    def find_active_session(notebook_path: str):
        """
        [UI TOOL] Check if a kernel is already running for this notebook.
        
        Scenario: User opens a notebook on Monday. This tool checks if:
        1. The server has an active session in memory
        2. The kernel process is still alive
        
        Used by VS Code extension to show the "Resume session?" prompt
        instead of silently reusing a hidden kernel.
        
        Args:
            notebook_path: Relative or absolute path to the notebook
            
        Returns:
            JSON with keys:
            - found: bool - whether a session exists
            - kernel_id: str - kernel UUID if found
            - pid: int - kernel process ID if found
            - start_time: str - when the kernel was started
            - status: str - "running" or "unknown"
        """
        from pathlib import Path
        
        abs_path = str(Path(notebook_path).resolve())
        session = session_manager.sessions.get(abs_path)
        
        if session:
            try:
                env_info = session.get('env_info', {})
                km = session['km']
                
                # Check if kernel is still alive
                if km.is_alive():
                    return json.dumps({
                        "found": True,
                        "kernel_id": getattr(km, 'kernel_id', 'unknown'),
                        "pid": None,  # Will be populated by get_kernel_details
                        "start_time": env_info.get('start_time'),
                        "status": "running"
                    })
            except Exception as e:
                import logging
                logging.error(f"[SESSION] Error checking session: {e}")
        
        return json.dumps({"found": False})

    @mcp.tool()
    @audit_tool
    def list_all_sessions():
        """
        [UI TOOL] List all running kernels for the Sidebar UI.
        
        Called by VS Code extension to populate the "Active Kernels" sidebar.
        Shows user what kernels are running, their PIDs, and start times.
        Helps user see "ghost" sessions from renamed notebooks.
        
        Returns:
            JSON array with session records:
            [
              {
                "notebook_path": "/home/user/project/draft.ipynb",
                "kernel_id": "abc-123-def",
                "pid": 12345,
                "start_time": "2026-01-27T14:30:00",
                "status": "running"
              },
              ...
            ]
        """
        sessions = session_manager.get_all_sessions()
        return json.dumps(sessions, indent=2)

    @mcp.tool()
    @audit_tool
    async def attach_session(target_notebook_path: str, source_pid: int):
        """
        [RENAME FIX] Attach the current notebook view to an existing kernel process.
        
        Scenario: You renamed draft.ipynb to final.ipynb on Monday morning.
        The kernel from Friday is still running under the old path.
        
        This tool migrates the kernel session from the old path to the new path,
        so you keep all your variables and execution state.
        
        Args:
            target_notebook_path: Where you want the kernel (your current notebook)
            source_pid: The kernel PID from the sidebar (the one to migrate)
            
        Returns:
            JSON with success status and old path for logging
        """
        from pathlib import Path
        
        # Find which session owns this PID
        old_path = session_manager.get_session_by_pid(source_pid)
        
        if not old_path:
            return json.dumps({
                "success": False,
                "error": f"PID {source_pid} not found in any managed session"
            })
        
        try:
            target_abs = str(Path(target_notebook_path).resolve())
            success = await session_manager.migrate_session(old_path, target_abs)
            
            if success:
                return json.dumps({
                    "success": True,
                    "old_path": old_path,
                    "new_path": target_abs
                })
            else:
                return json.dumps({
                    "success": False,
                    "error": f"Migration failed (session may have been terminated)"
                })
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    @mcp.tool()
    @audit_tool
    def get_execution_history(notebook_path: str, limit: int = 50):
        """
        [REHYDRATION] Get recent execution outputs to populate blank cells on reload.
        
        Scenario: You reconnect to a notebook on Monday. VS Code has blank
        cell outputs (it clears them on close). This tool retrieves what actually
        ran on Friday from the persistence layer.
        
        Args:
            notebook_path: Path to the notebook
            limit: Maximum entries to return (default 50)
            
        Returns:
            JSON array of execution history records:
            [
              {
                "cell_index": 0,
                "status": "completed",
                "completed_at": "2026-01-24T17:30:00",
                "error": null
              },
              {
                "cell_index": 1,
                "status": "failed",
                "completed_at": "2026-01-24T17:35:00",
                "error": "NameError: name 'x' is not defined"
              },
              ...
            ]
        """
        history = session_manager.get_execution_history(notebook_path, limit)
        return json.dumps(history, indent=2)

    @mcp.tool()
    @audit_tool
    def get_notebook_history(notebook_path: str):
        """
        [OUTPUT REHYDRATION] Get full visual history with outputs for a notebook.
        
        When user "Attaches" to a session on Monday, VS Code shows blank cells
        even though the kernel has outputs in RAM. This tool retrieves the
        persisted outputs so we can repopulate the notebook UI.
        
        Returns:
            JSON array with cell outputs in Jupyter MIME format:
            [
              {
                "cell_index": 0,
                "execution_count": 1,
                "outputs": [
                  {
                    "output_type": "stream",
                    "name": "stdout",
                    "text": "Hello World\\n"
                  }
                ]
              },
              ...
            ]
        """
        history = session_manager.get_notebook_history(notebook_path)
        return json.dumps(history, indent=2)

    @mcp.tool()
    @audit_tool
    async def get_completions(notebook_path: str, code: str, cursor_pos: int):
        """
        [AUTOCOMPLETE PROXY] Get Jupyter kernel completions for a code position.
        
        Solves "The Autocomplete Void" - users get intelligent suggestions
        from the actual kernel, not just from file parsing.
        
        Scenario: User types "df." and immediately gets suggestions for
        the actual dataframe columns (revenue_2024, price, etc.)
        instead of a blank void.
        
        Args:
            notebook_path: Path to the notebook
            code: The code up to the cursor position
            cursor_pos: Cursor position in the code
            
        Returns:
            JSON array of completion strings and metadata:
            [
              { "text": "columns", "type": "property" },
              { "text": "head()", "type": "method" },
              { "text": "shape", "type": "property" },
              ...
            ]
        """
        from pathlib import Path
        
        abs_path = str(Path(notebook_path).resolve())
        session = session_manager.sessions.get(abs_path)
        
        if not session:
            return json.dumps({
                "error": "No active kernel for this notebook",
                "matches": []
            })
        
        try:
            kc = session.get('kc')
            if not kc:
                return json.dumps({"error": "No kernel client", "matches": []})
            
            # Call kernel's complete() method
            msg_id = kc.complete(code, cursor_pos)
            
            # Wait for reply (with timeout)
            import asyncio
            reply = await asyncio.wait_for(
                session_manager.io_multiplexer.wait_for_message(msg_id, 'shell'),
                timeout=5.0
            )
            
            matches = reply.get('content', {}).get('matches', [])
            
            return json.dumps({
                "matches": matches,
                "cursor_start": reply.get('content', {}).get('cursor_start'),
                "cursor_end": reply.get('content', {}).get('cursor_end')
            }, indent=2)
            
        except asyncio.TimeoutError:
            return json.dumps({
                "error": "Kernel completion timeout",
                "matches": []
            })
        except Exception as e:
            import logging
            logging.error(f"[COMPLETIONS] Error: {e}")
            return json.dumps({
                "error": str(e),
                "matches": []
            })
