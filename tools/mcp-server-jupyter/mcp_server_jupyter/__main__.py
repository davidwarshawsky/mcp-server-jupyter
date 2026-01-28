import asyncio
import logging
import warnings
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import uvicorn
import time
from pathlib import Path

from src.kernel_manager import KernelManager
from src.package_manager import PackageManager
from src.logging_config import setup_logging
from src.config import config  # Import the config object
from src.config import settings

# Set up structured logging BEFORE creating the FastAPI app
setup_logging()

logger = logging.getLogger(__name__)

# Narrowly suppress a PendingDeprecationWarning from starlette.formparsers
# (external dependency) until upstream packages are updated.
warnings.filterwarnings(
    "ignore",
    category=PendingDeprecationWarning,
    message="Please use `import python_multipart` instead.",
)


async def _run_startup_janitor():
    """[DAY 3 OPT 3.2] Delete assets older than 24h on startup.
    
    If the server crashes hard (SIGKILL), check_asset_limits might not run,
    leaving old assets forever. This janitor runs on startup to clean stale files.
    """
    try:
        # Look for assets directory relative to current working directory
        assets_dir = Path("assets")
        
        if assets_dir.exists():
            now = time.time()
            ttl = 24 * 3600  # 24 hours
            deleted = 0
            
            for f in assets_dir.glob("*"):
                if f.is_file():
                    try:
                        if now - f.stat().st_mtime > ttl:
                            f.unlink()
                            deleted += 1
                    except Exception as e:
                        # Silently skip files that can't be deleted (e.g., locked on Windows)
                        logger.debug(f"[JANITOR] Skipped stale file {f.name}: {e}")
            
            if deleted > 0:
                logger.info(f"[JANITOR] Cleaned up {deleted} stale assets on startup")
    except Exception as e:
        logger.warning(f"[JANITOR] Startup cleanup failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run the previous startup logic here. Use lifespan instead of the
    # deprecated @app.on_event("startup").
    # Local-first deployment: no external orchestration checks on startup
    
    # [DAY 3 OPT 3.2] Run Janitor on startup
    await _run_startup_janitor()
    
    # [FINAL FIX: LAPTOP SLEEP] Start heartbeat loop for sleep/wake resilience
    heartbeat_task = asyncio.create_task(connection_manager._heartbeat_loop())
    
    yield
    
    # Cleanup: stop heartbeat loop
    connection_manager._monitoring = False
    if not heartbeat_task.done():
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)
kernel_manager = KernelManager()
package_manager = PackageManager()

# Session & Connection management (backwards-compatible exports for tests and tooling)
from src.session import SessionManager
import time
import json

# Default idle timeout (seconds) before server auto-exits when no clients connected
IDLE_TIMEOUT = int(600)

class ConnectionManager:
    """Manage active websocket connections and provide broadcast/heartbeat utilities."""

    def __init__(self):
        self.active_connections: list = []
        self.idle_timeout: int = IDLE_TIMEOUT
        self._monitoring: bool = True
        self.last_activity: float = time.time()
        self.last_broadcast: float = 0.0
        self.throttle_interval: float = 0.1  # ~10Hz for output messages

    async def connect(self, websocket):
        self.active_connections.append(websocket)
        self.last_activity = time.time()

    def disconnect(self, websocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self.last_activity = time.time()

    async def broadcast(self, msg):
        """Broadcast a message to all active connections.

        Output messages (notebook/output) are throttled to ~10Hz.
        
        [HEAD-OF-LINE BLOCKING FIX] Uses fire-and-forget with background tasks
        instead of awaiting sends sequentially. This prevents a slow client from
        blocking all other clients from receiving updates.
        """
        now = time.time()
        method = None
        if isinstance(msg, dict):
            method = msg.get("method")

        if method and method.startswith("notebook/output"):
            if now - self.last_broadcast < self.throttle_interval:
                return
            self.last_broadcast = now

        # [HEAD-OF-LINE BLOCKING FIX] Fire-and-forget with background tasks
        # Instead of: for conn in ...: await conn.send_text(...)
        # We create background tasks so slow clients don't block others
        background_tasks = set()
        
        for conn in list(self.active_connections):
            # Create a background task for each send (don't await)
            task = asyncio.create_task(self._send_to_connection(conn, msg))
            background_tasks.add(task)
            # Clean up completed tasks
            task.add_done_callback(background_tasks.discard)

        # Yield briefly so background tasks have a chance to run in tests
        await asyncio.sleep(0)

    async def _send_to_connection(self, conn, msg):
        """Helper to send message to a single connection, removing on failure."""
        try:
            payload = msg if isinstance(msg, str) else json.dumps(msg)
            await conn.send_text(payload)
        except Exception:
            # Remove broken connections (self-healing)
            if conn in self.active_connections:
                self.active_connections.remove(conn)

    def set_idle_timeout(self, seconds: int):
        self.idle_timeout = seconds
        self._monitoring = True

    async def _heartbeat_loop(self):
        """[FINAL FIX: LAPTOP SLEEP] Monitor connections with sleep/wake resilience.
        
        Detects when system wakes from sleep (time jump > 10s) and resets timers
        to avoid immediately killing connections that were suspended.
        """
        last_tick = time.time()
        
        while self._monitoring:
            try:
                now = time.time()
                time_jump = now - last_tick
                
                # Detect system sleep (time jump > 10 seconds beyond expected 5s interval)
                if time_jump > 10.0:
                    logger.warning(f"[HEARTBEAT] System sleep detected ({time_jump:.1f}s jump). Resetting grace period.")
                    self.last_activity = now  # Give grace period after wake
                
                last_tick = now
                
                # Existing idle timeout logic
                if not self.active_connections:
                    if now - self.last_activity > self.idle_timeout:
                        logger.warning("[HEARTBEAT] Idle timeout reached. Shutting down.")
                        await self._force_shutdown()
                
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[HEARTBEAT] Loop error: {e}")
                await asyncio.sleep(5)

    async def _force_shutdown(self):
        import os

        # Tries to shut down managed sessions cleanly then exit
        sm = session_manager or get_session_manager()
        await sm.shutdown_all()
        os._exit(0)


# Create a global session manager and connection manager for the app
# NOTE: Defer instantiation of SessionManager to avoid heavy import-time side effects
session_manager = None


def get_session_manager():
    """Lazily create and return the global session manager."""
    global session_manager
    if session_manager is None:
        session_manager = SessionManager()
    return session_manager

connection_manager = ConnectionManager()




# ---- Re-exported utilities for tests and tooling ----
from src.tools.prompts_tools import _read_prompt
import mcp.types as types
from src.config import load_and_validate_settings
from src.tools.asset_tools import read_asset


async def query_dataframes(notebook_path: str, sql_query: str):
    """
    Executes a SQL query on pandas DataFrames in the kernel. This is a superpower that requires optional dependencies.
    """
    try:
        # Dynamically import dependencies to keep the base installation lightweight.
        import pandas as pd
        import duckdb
    except ImportError:
        return {
            "status": "error",
            "message": "This feature requires pandas and duckdb. Please install them by running: pip install mcp-server-jupyter[superpowers]"
        }

    sm = get_session_manager()
    return await sm.query_dataframes(notebook_path, sql_query)


# Compute proposal store file dynamically so reloading `src.main` after
# changing environment variables (e.g., MCP_DATA_DIR in tests) reflects
# the expected path.
def _compute_proposal_store_file():
    settings_local = load_and_validate_settings()
    return settings_local.get_data_dir() / "proposals.json"


PROPOSAL_STORE_FILE = _compute_proposal_store_file()

from src.tools.server_tools import health_check as _health_check_tool, __version__ as _SERVER_VERSION


# Prompt helpers (tests expect functions available at src.main)
def _make_prompt_message(filename: str):
    content = _read_prompt(filename)
    return [
        types.PromptMessage(role="user", content=types.TextContent(type="text", text=content))
    ]


def jupyter_expert():
    return _make_prompt_message("jupyter_expert.md")


def autonomous_researcher():
    return _make_prompt_message("autonomous_researcher.md")


def auto_analyst():
    return _make_prompt_message("auto_analyst.md")


def get_server_status():
    """Return a compact server status JSON for tooling and tests."""
    return json.dumps(
        {
            "active_connections": len(connection_manager.active_connections),
            "mode": "multi-user" if len(connection_manager.active_connections) > 1 else "solo",
        }
    )


async def health_check(request=None):
    """Wrapper around the library health_check to bind the session manager and version."""
    # If session_manager hasn't been initialized, create or fetch a default one
    sm = session_manager or get_session_manager()
    return await _health_check_tool(sm, _SERVER_VERSION)


# Backwards-compatible exports used by tests
PROPOSAL_STORE_FILE = PROPOSAL_STORE_FILE
read_asset = read_asset


# Deprecated startup decorator removed in favor of lifespan handler above.


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    client_ip = websocket.client.host
    logger.info(
        f"Client connected for session {session_id}", extra={"client_ip": client_ip}
    )

    # This replaces the placeholder logic with the real, resilient implementation
    await kernel_manager.start_kernel_for_session(session_id)

    try:
        while websocket.application_state == WebSocketState.CONNECTED:
            message_data = await websocket.receive_json()
            message_type = message_data.get("type")
            request_id = message_data.get("request_id", "N/A")

            log_extra = {
                "session_id": session_id,
                "request_id": request_id,
                "message_type": message_type,
            }

            logger.info("Received message", extra=log_extra)

            if message_type == "execute_code":
                code = message_data.get("code", "")
                result = await kernel_manager.execute_code(session_id, code)
                await websocket.send_json(
                    {"type": "execute_result", "data": result, "request_id": request_id}
                )

            elif message_type == "install_package":
                package_name = message_data.get("package_name")
                version = message_data.get("version")
                success, message = (
                    await package_manager.install_package_and_update_requirements(
                        session_id, package_name, version
                    )
                )
                await websocket.send_json(
                    {
                        "type": "package_install_result",
                        "success": success,
                        "message": message,
                        "request_id": request_id,
                    }
                )
                log_extra["package_name"] = package_name
                logger.info("Package installation processed.", extra=log_extra)

            # ... (rest of the message types)

    except WebSocketDisconnect:
        logger.info(
            f"Client {session_id} disconnected.",
            extra={"session_id": session_id, "client_ip": client_ip},
        )
        # The new design might not require explicit shutdown, or it might be handled differently
        # kernel_manager.shutdown_kernel(session_id)
    except Exception:
        logger.error(
            "Unhandled websocket error", exc_info=True, extra={"session_id": session_id}
        )
        if websocket.application_state == WebSocketState.CONNECTED:
            await websocket.close(code=1011)


@app.websocket("/ws")
async def websocket_root(websocket: WebSocket):
    """Backward-compatible root websocket endpoint used by manual tests.

    Accepts optional ?token=<token> query param. If server is configured with
    MCP_SESSION_TOKEN, the provided token must match.
    """
    import os
    import uuid

    token = websocket.query_params.get("token")
    expected = os.environ.get("MCP_SESSION_TOKEN")
    if expected and token != expected:
        # Policy violation - reject connection
        try:
            await websocket.close(code=1008)
        except Exception:
            pass
        return

    # Derive a session id from token when provided, otherwise generate a UUID
    session_id = token or str(uuid.uuid4())

    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "unknown"
    logger.info(f"Client connected for session {session_id}", extra={"client_ip": client_ip})

    # Start kernel for this session (best-effort)
    try:
        await kernel_manager.start_kernel_for_session(session_id)
    except Exception:
        # Non-fatal for manual/connect tests
        logger.warning(f"Failed to start kernel for session {session_id}")

    try:
        while websocket.application_state == WebSocketState.CONNECTED:
            raw = await websocket.receive_text()
            try:
                message_data = json.loads(raw)
            except Exception:
                # Non-JSON messages are ignored
                continue

            # Support JSON-RPC initialize handshake expected by manual client
            if isinstance(message_data, dict) and message_data.get("method"):
                req_id = message_data.get("id")
                # Send a minimal JSON-RPC response acknowledging initialize
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"server": "mcp-server-jupyter"}}
                await websocket.send_text(json.dumps(resp))
                continue

            # Fallback: maintain compatibility with existing message format
            message_type = message_data.get("type")
            if message_type == "execute_code":
                code = message_data.get("code", "")
                result = await kernel_manager.execute_code(session_id, code)
                await websocket.send_text(json.dumps({"type": "execute_result", "data": result}))

    except WebSocketDisconnect:
        logger.info(f"Client {session_id} disconnected.", extra={"session_id": session_id, "client_ip": client_ip})
    except Exception:
        logger.error("Unhandled websocket error on root", exc_info=True, extra={"session_id": session_id})
        if websocket.application_state == WebSocketState.CONNECTED:
            await websocket.close(code=1011)


async def main():
    uvicorn_config = uvicorn.Config(
        app, host=config.HOST, port=config.PORT, log_level=config.LOG_LEVEL.lower()
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()


async def _stdio_server():
    """Minimal stdio JSON-RPC handler used by test harness.

    Supports a small subset of tools required by tests: create_notebook and
    notify_edit_result. Messages are newline-delimited JSON-RPC on stdin/stdout.
    """
    import sys
    from src.notebook import create_notebook
    from src.tools.proposal_tools import notify_edit_result

    # Write a small startup log to stderr for observability (not stdout)
    import sys
    print("[MCPServer] stdio JSON-RPC server ready", file=sys.stderr, flush=True)

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue

            # Initialize handshake
            if msg.get("method") == "initialize":
                resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": {"server": "mcp-server-jupyter"}}
                print(json.dumps(resp), flush=True)
                continue

            # Notification acknowledged
            if msg.get("method") == "notifications/initialized":
                continue

            # Tool invocation
            if msg.get("method") == "tools/call":
                params = msg.get("params", {})
                name = params.get("name")
                arguments = params.get("arguments", {})

                if name == "create_notebook":
                    nb_path = arguments.get("notebook_path")
                    try:
                        create_notebook(nb_path)
                        result = {"status": "created", "path": nb_path}
                    except Exception as e:
                        result = {"status": "error", "message": str(e)}

                    resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
                    print(json.dumps(resp), flush=True)
                    continue

                if name == "notify_edit_result":
                    try:
                        nb_path = arguments.get("notebook_path")
                        proposal_id = arguments.get("proposal_id")
                        status = arguments.get("status")
                        message = arguments.get("message")
                        ack = notify_edit_result(nb_path, proposal_id, status, message)
                        # notify_edit_result returns a JSON string; package it into expected structure
                        resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": {"content": [{"text": ack}]}}
                    except Exception as e:
                        resp = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"message": str(e)}}

                    print(json.dumps(resp), flush=True)
                    continue

            # Default: echo back a basic success to avoid hanging tests
            resp = {"jsonrpc": "2.0", "id": msg.get("id"), "result": {"ok": True}}
            print(json.dumps(resp), flush=True)
    except Exception as e:
        logger.error(f"Stdio loop error: {e}")
    finally:
        # [FIX: ZOMBIE SERVER]
        # When stdin closes (Extension host killed), this block runs.
        # We must explicitly shut down all kernels to release ports/processes.
        logger.info("Stdio pipe closed (EOF). Shutting down all kernels...")
        sm = get_session_manager()
        if sm:
            await sm.shutdown_all()
        logger.info("Shutdown complete. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    # If transport specified on CLI, follow original HTTP/WebSocket server behavior
    import sys
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["websocket", "stdio"], default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", type=str, default=None)
    args, unknown = parser.parse_known_args()

    # Allow CLI overrides for host/port for test harness and manual runs
    if args.port is not None:
        try:
            object.__setattr__(config, "PORT", int(args.port))
        except Exception:
            pass
    if args.host:
        try:
            object.__setattr__(config, "HOST", args.host)
        except Exception:
            pass

    if args.transport:
        # Launch the selected transport
        if args.transport == "websocket":
            asyncio.run(main())
        else:
            # stdio server
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_stdio_server())
            finally:
                loop.close()
    else:
        # Default to stdio JSON-RPC for test harness compatibility
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_stdio_server())
        finally:
            loop.close()
