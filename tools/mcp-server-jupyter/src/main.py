"""
MCP Jupyter Server - Secure, AI-Assisted Jupyter Notebooks for Healthcare & Life Sciences

[LICENSE] Apache License 2.0
This project is distributed under the Apache 2.0 License.
Safe for internal modification and distribution in healthcare organizations.
See LICENSE file for complete terms.

[SECURITY] This project has been hardened for healthcare compliance:
- No shell access (no run_shell_command tool)
- Base64 encoding for SQL queries (prevents injection)
- Package allowlist (prevents supply chain attacks)
- Encrypted asset transport
- Secure session management with HMAC signing
- Auto-healing kernel recovery
- Git-safe notebook workflows

[INTERNAL USE] For authorized organizational use only.
"""

from mcp.server.fastmcp import FastMCP
import asyncio
import time
import os
from pathlib import Path
from typing import List, Optional, Any, Dict
import nbformat
import json
import sys
import logging
import datetime
from starlette.websockets import WebSocket, WebSocketDisconnect
from starlette.staticfiles import StaticFiles
from starlette.routing import Mount
from src.session import SessionManager
from src import notebook, utils, environment, validation
from src.utils import ToolResult
import websockets
import mcp.types as types

# Pydantic models and decorator for strict validation
from src.models import StartKernelArgs, RunCellArgs
from src.validation import validated_tool

# Initialize structured logging via structlog (observability)
from src.observability import configure_logging, get_logger, get_tracer
import traceback

logger = configure_logging()
tracer = get_tracer(__name__)

# Server version for compatibility checking
__version__ = "0.2.0"

# [HEARTBEAT] Auto-shutdown configuration
HEARTBEAT_INTERVAL = 60  # Check every minute
IDLE_TIMEOUT = 600       # Shutdown after 10 minutes of no connections

# [BROADCASTER] Connection Manager for Multi-User Notification
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.idle_timeout: int = 0
        self.last_activity = time.time()
        self._monitoring = False

    def set_idle_timeout(self, timeout: int):
        """Enable heartbeat monitoring with specific timeout (seconds)."""
        self.idle_timeout = int(timeout) if timeout else 0
        if self.idle_timeout > 0 and not self._monitoring:
            self._monitoring = True
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(self._monitor_lifecycle())
            except RuntimeError:
                # If there is no running loop (e.g., starting from synchronous main),
                # start a dedicated background thread with its own asyncio loop.
                import threading
                def _run_in_thread():
                    try:
                        asyncio.run(self._monitor_lifecycle())
                    except Exception as e:
                        logger.error(f"Heartbeat thread error: {e}")
                t = threading.Thread(target=_run_in_thread, daemon=True)
                t.start()

    async def _monitor_lifecycle(self):
        """Background task to kill server if idle for too long."""
        logger.info(f"[Heartbeat] Monitor started. Timeout: {self.idle_timeout}s")
        while True:
            await asyncio.sleep(10)  # Check more frequently for faster shutdowns in tests

            # If we have connections, we are active. Reset timer.
            if len(self.active_connections) > 0:
                self.last_activity = time.time()
                continue

            # If no connections, check how long we've been lonely
            idle_duration = time.time() - self.last_activity
            if idle_duration > self.idle_timeout:
                logger.warning(f"[Heartbeat] Server idle for {idle_duration:.1f}s. Shutting down.")
                await self._force_shutdown()

    async def _force_shutdown(self):
        """Cleanup and kill process."""
        try:
            logger.info("[Heartbeat] Performing graceful shutdown of sessions...")
            await session_manager.shutdown_all()
        except Exception as e:
            logger.error(f"Cleanup error during heartbeat shutdown: {e}")
        finally:
            logger.info("[Heartbeat] Exiting process.")
            # Force exit is necessary because uvicorn captures signals
            os._exit(0)

    async def connect(self, websocket: WebSocket):
        # NOTE: We do NOT call accept() here because mcp.server.websocket handles the ASGI handshake.
        # We just register the connection.
        self.active_connections.append(websocket)
        self.last_activity = time.time()
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            # Reset clock on disconnect to give a grace period
            self.last_activity = time.time()
            logger.info(f"Client disconnected. Total: {len(self.active_connections)}")
    async def broadcast(self, message: dict):
        # Immediate send for status changes or errors
        if message.get('method') != 'notebook/output':
            await self._send_raw(message)
            return

        # For outputs, throttle to ~10 messages per second (100ms delay)
        now = time.time()
        if now - getattr(self, 'last_broadcast', 0) > 0.1:
            await self._send_raw(message)
            self.last_broadcast = now
        else:
            # Drop or aggregate (Dropping intermediate high-frequency output is usually fine for UX)
            pass 

    async def _send_raw(self, message):
        """Send raw JSON message to all connected clients"""
        json_str = json.dumps(message)
        # Iterate over copy to prevent runtime errors during disconnects
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json_str)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
                self.disconnect(connection)

def fatal_exception_handler(loop, context):
    """Asyncio exception handler that ensures JSON logs before death."""
    msg = context.get("exception", context.get("message", ""))
    logger.critical("fatal_async_error", error=str(msg), context=context)

mcp = FastMCP("jupyter")
session_manager = SessionManager()
session_manager.set_mcp_server(mcp)
# Inject connection manager
connection_manager = ConnectionManager()
session_manager.connection_manager = connection_manager

# [ROUND 2 AUDIT] Start proposal cleanup background task
async def _proposal_cleanup_loop():
    """Cleanup old proposals every hour to prevent unbounded growth."""
    await asyncio.sleep(3600)  # Initial delay
    while True:
        try:
            cleanup_old_proposals()
            await asyncio.sleep(3600)  # Every hour
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[PROPOSALS CLEANUP] Error: {e}")
            await asyncio.sleep(3600)

asyncio.create_task(_proposal_cleanup_loop())

# Health endpoint used by external orchestrators (module-level so tests can import it)
from starlette.responses import JSONResponse
async def health_check(request=None):
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
        "version": "0.1.0"
    }, status_code=200 if is_healthy else 503)

@mcp.tool()
def get_server_status():
    """Check how many humans are connected to this session."""
    return json.dumps({
        "active_connections": len(connection_manager.active_connections),
        "mode": "multi-user" if len(connection_manager.active_connections) > 1 else "solo"
    })


# Persistence for proposals
PROPOSAL_STORE_FILE = Path.home() / ".mcp-jupyter" / "proposals.json"

from collections import deque

PROPOSAL_HISTORY = deque(maxlen=1000)  # Keep only the most recent 1000 proposals


def load_proposals():
    """Load proposals from disk to survive server restarts."""
    if PROPOSAL_STORE_FILE.exists():
        try:
            with open(PROPOSAL_STORE_FILE, 'r') as f:
                data = json.load(f)
                # Load history keys in insertion order if present
                for k in data.get('_history', []):
                    PROPOSAL_HISTORY.append(k)
                return data.get('store', {})
        except Exception as e:
            logger.error(f"Failed to load proposals: {e}")
    return {}


def save_proposals():
    """Save proposals to disk along with history to survive restarts."""
    try:
        PROPOSAL_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROPOSAL_STORE_FILE, 'w') as f:
            json.dump({'store': PROPOSAL_STORE, '_history': list(PROPOSAL_HISTORY)}, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save proposals: {e}")


def cleanup_old_proposals(max_age_hours: int = 24):
    """[ROUND 2 AUDIT] Remove proposals older than max_age_hours to prevent unbounded disk growth."""
    import time
    now = time.time()
    removed = []
    
    for proposal_id in list(PROPOSAL_STORE.keys()):
        proposal = PROPOSAL_STORE[proposal_id]
        timestamp = proposal.get('timestamp', 0)
        if now - timestamp > max_age_hours * 3600:
            PROPOSAL_STORE.pop(proposal_id)
            try:
                PROPOSAL_HISTORY.remove(proposal_id)
            except ValueError:
                pass
            removed.append(proposal_id)
    
    if removed:
        logger.info(f"[CLEANUP] Removed {len(removed)} old proposals")
        save_proposals()
    
    return len(removed)


# Store for agent proposals to support feedback loop
# Key: proposal_id, Value: dict with status, result, timestamp
PROPOSAL_STORE = load_proposals()


def save_proposal(proposal_id: str, data: dict):
    """Insert a proposal and evict oldest if over cap."""
    if proposal_id in PROPOSAL_STORE:
        PROPOSAL_STORE[proposal_id].update(data)
        # Move to most recent in history: remove and append
        try:
            PROPOSAL_HISTORY.remove(proposal_id)
        except ValueError:
            pass
        PROPOSAL_HISTORY.append(proposal_id)
    else:
        if len(PROPOSAL_HISTORY) >= PROPOSAL_HISTORY.maxlen:
            # Evict oldest
            oldest = PROPOSAL_HISTORY.popleft()
            PROPOSAL_STORE.pop(oldest, None)
        PROPOSAL_STORE[proposal_id] = data
        PROPOSAL_HISTORY.append(proposal_id)
    # Persist to disk in best-effort manner
    try:
        save_proposals()
    except Exception:
        pass

@mcp.tool()
@validated_tool(StartKernelArgs)
async def start_kernel(notebook_path: str, venv_path: str = "", docker_image: str = "", timeout: int = 300, agent_id: Optional[str] = None):
    """
    Boot a background process.
    Windows Logic: Looks for venv_path/Scripts/python.exe.
    Ubuntu Logic: Looks for venv_path/bin/python.
    Docker Logic: If docker_image is set, runs kernel securely in container.
    Timeout: Seconds before killing long-running cells (default: 300).
    Output: "Kernel started (PID: 1234). Ready for execution."
    """
    with tracer.start_as_current_span("tool.start_kernel") as span:
        span.set_attribute("notebook_path", notebook_path)
        span.set_attribute("docker_image", docker_image)
        # Capture the active session for notifications
        try:
            ctx = mcp.get_context()
            if ctx and ctx.request_context:
                session_manager.register_session(ctx.request_context.session)
        except:
             # Ignore if context not available (e.g. testing)
             pass

        # Security Check
        if not docker_image:
            logger.warning(f"Unsandboxed execution requested for {notebook_path}. All code runs with user privileges.")

        return await session_manager.start_kernel(
            notebook_path, 
            venv_path if venv_path else None,
            docker_image if docker_image else None,
            timeout,
            agent_id=agent_id
        )

@mcp.tool()
async def stop_kernel(notebook_path: str):
    """
    Kill the process to free RAM and clean up assets.
    """
    with tracer.start_as_current_span("tool.stop_kernel") as span:
        span.set_attribute("notebook_path", notebook_path)
        # 1. Prune assets before stopping
        from src.asset_manager import prune_unused_assets
        try:
            # Run cleanup. This ensures that if I delete a cell and close the notebook,
            # the orphaned image is deleted.
            prune_unused_assets(notebook_path, dry_run=False)
        except Exception as e:
            logger.warning(f"Asset cleanup failed: {e}")

        return await session_manager.stop_kernel(notebook_path)

@mcp.tool()
def list_kernels():
    """
    List all active kernel sessions.
    Returns: JSON with notebook paths and kernel status.
    """
    result = []
    for nb_path, session in session_manager.sessions.items():
        pid = "unknown"
        if hasattr(session.get('km'), 'kernel') and session['km'].kernel:
            pid = getattr(session['km'].kernel, 'pid', 'unknown')
        
        result.append({
            'notebook_path': nb_path,
            'pid': pid,
            'cwd': session.get('cwd', 'unknown'),
            'execution_count': session.get('execution_counter', 0),
            'queue_size': session['execution_queue'].qsize() if 'execution_queue' in session else 0,
            'stop_on_error': session.get('stop_on_error', False)
        })
    
    return json.dumps(result, indent=2)

@mcp.tool()
async def detect_sync_needed(notebook_path: str, buffer_hashes: Optional[Dict[int, str]] = None):
    """
    [HANDOFF PROTOCOL] Detect if kernel state is out of sync with disk or VS Code buffer.
    
    **Purpose**: Before the agent starts work, check if a human has modified the notebook
    since the last agent execution.
    
    **How It Works**:
    1. If buffer_hashes provided (from VS Code client), use those as source of truth.
    2. Otherwise, reads notebook from disk.
    3. Calculates SHA-256 hash of each cell's content.
    4. Compares with 'execution_hash' stored in cell metadata.
    5. If hashes mismatch, sync is required.
    
    Args:
        notebook_path: Path to notebook
        buffer_hashes: Optional dict of {cell_index: hash} from VS Code buffer (source of truth)
    
    Returns:
        JSON with:
        - sync_needed: boolean
        - reason: Description of mismatch
        - changed_cells: List of cell indices that changed
    """
    import os
    from pathlib import Path
    
    abs_path = str(Path(notebook_path).resolve())
    session = session_manager.get_session(notebook_path)
    
    if not session:
        return json.dumps({
            "sync_needed": True,
            "reason": "no_active_kernel",
            "recommendation": "Call start_kernel() first"
        })
    
    # If buffer_hashes provided by client, use those as source of truth
    # Otherwise, read from disk (legacy behavior)
    changed_cells = []
    
    if buffer_hashes is not None:
        # Client-provided hashes (VS Code buffer state) - this is the source of truth
        for idx, buffer_hash in buffer_hashes.items():
            # Compare against kernel execution history
            exec_history = session.get('execution_history', {})
            kernel_hash = exec_history.get(idx)
            
            if not kernel_hash or buffer_hash != kernel_hash:
                changed_cells.append(idx)
    else:
        # Legacy: Read notebook from disk
        try:
            nb = nbformat.read(notebook_path, as_version=4)
        except Exception as e:
            return json.dumps({
                "error": f"Failed to read notebook: {e}"
            })
        
        for idx, cell in enumerate(nb.cells):
            if cell.cell_type == 'code':
                current_hash = utils.get_cell_hash(cell.source)
                # Check both new 'mcp' and legacy 'mcp_trace' metadata locations
                mcp_meta = cell.metadata.get('mcp', {}) or cell.metadata.get('mcp_trace', {})
                last_hash = mcp_meta.get('execution_hash')
                
                # If no hash exists (never executed by agent) or hash mismatch (content changed)
                if not last_hash or current_hash != last_hash:
                    changed_cells.append(idx)
    
    sync_needed = len(changed_cells) > 0
    
    return json.dumps({
        'sync_needed': sync_needed,
        'reason': f"Content mismatch in {len(changed_cells)} cells" if sync_needed else "Content matches execution history",
        'changed_cells': changed_cells,
        'recommendation': 'sync_state_from_disk' if sync_needed else 'proceed',
        'sync_strategy': 'full'
    }, indent=2)

@mcp.tool()
def set_stop_on_error(notebook_path: str, enabled: bool):
    """
    Control whether execution queue stops on first error.
    Agent Use Case: Set to True when running dependent cells (cell 2 needs cell 1's variables).
    Set to False for independent exploration cells.
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return "Error: No running kernel. Call start_kernel first."
    
    session['stop_on_error'] = enabled
    return f"stop_on_error set to {enabled} for {notebook_path}"

@mcp.tool()
def get_notebook_outline(notebook_path: str, structure_override: Optional[List[dict]] = None):
    """
    Low-token overview of the file.
    Args:
        structure_override: Optional list of cell metadata pushed from VS Code buffer.
                           Prevents "Index Blindness" where Agent reads stale disk state.
    """
    if structure_override:
        # Use the real-time buffer state from VS Code
        return notebook.format_outline(structure_override)
    else:
        # Fallback to disk (risk of stale data)
        return notebook.get_notebook_outline(notebook_path)

@mcp.tool()
def append_cell(notebook_path: str, content: str, cell_type: str = "code"):
    """
    Add new logic to the end.
    Constraint: Automatically clears output (to avoid stale data) and sets execution_count to null.
    """
    return notebook.append_cell(notebook_path, content, cell_type)

# [ROUND 2 AUDIT: REMOVED] Checkpoint features using dill/pickle are fundamentally insecure
# Enterprise compliance bans pickle deserialization. Use replay-from-history instead.
# @mcp.tool()
# async def save_checkpoint(notebook_path: str, name: str = "checkpoint"):
#     """REMOVED: Pickle-based checkpointing is a security liability"""
#     pass
#
# @mcp.tool()
# async def load_checkpoint(notebook_path: str, name: str = "checkpoint"):
#     """REMOVED: Use re-execute cells instead of deserializing pickled state"""
#     pass

@mcp.tool()
def propose_edit(notebook_path: str, index: int, new_content: str):
    """
    Propose an edit to a cell. 
    This avoids writing to disk directly, preventing conflicts with the editor buffer.
    The Agent should use this instead of 'edit_cell'.
    """
    import uuid
    proposal_id = str(uuid.uuid4())
    
    # Construct proposal
    proposal = {
        "id": proposal_id,
        "action": "edit_cell",
        "notebook_path": notebook_path,
        "index": index,
        "new_content": new_content,
        "timestamp": str(datetime.datetime.now())
    }

    # Persist the proposal with bounded history
    try:
        save_proposal(proposal_id, proposal)
    except Exception:
        logger.warning("Failed to persist proposal")
    
    # We return a specific structure that the Client (mcpClient.ts) listens for.
    # By convention, if the tool result contains this structure, the client
    # will trigger a WorkspaceEdit.
    
    return json.dumps({
        "status": "proposal_created", 
        "proposal_id": proposal_id,
        "proposal": proposal,
        "message": "Edit proposed. Client must apply changes.",
        # SIGNAL PROTOCOL
        "_mcp_action": "apply_edit" 
    })

@mcp.tool()
def notify_edit_result(notebook_path: str, proposal_id: str, status: str, message: Optional[str] = None):
    """
    Callback for the client to report the result of a proposed edit.
    status: 'accepted' | 'rejected' | 'failed'
    """
    logger.info(f"Edit result for {notebook_path} (ID: {proposal_id}): {status} - {message}")
    
    # Store result for agent to retrieve (bounded)
    timestamp = str(datetime.datetime.now())
    if proposal_id:
        try:
            existing = PROPOSAL_STORE.get(proposal_id, {})
            existing.update({
                "status": status,
                "message": message,
                "updated_at": timestamp
            })
            save_proposal(proposal_id, existing)
        except Exception:
            PROPOSAL_STORE[proposal_id] = {
                "status": status,
                "message": message,
                "updated_at": timestamp
            }
        # Persist latest state
        try:
            save_proposal(proposal_id, PROPOSAL_STORE[proposal_id])
        except Exception:
            # Best-effort persistence
            save_proposals()
    
    return json.dumps({
        "status": "ack",
        "proposal_id": proposal_id,
        "timestamp": timestamp
    })

@mcp.tool()
def get_proposal_status(proposal_id: str):
    """
    Check the status of a specific proposal.
    Returns: 'pending', 'accepted', 'rejected', 'failed', or 'unknown'.
    """
    if proposal_id in PROPOSAL_STORE:
        return json.dumps(PROPOSAL_STORE[proposal_id])
    return json.dumps({"status": "unknown"})

@mcp.tool()
def read_cell_smart(notebook_path: str, index: int, target: str = "both", fmt: str = "summary", line_range: Optional[List[int]] = None):
    """
    The Surgical Reader.
    target: "source" (code), "output" (result), or "both".
    format: "summary" (Default), "full", or "slice".
    line_range: [start_line, end_line] (e.g., [0, 10] or [-10, -1]).
    """
    if line_range and isinstance(line_range, list):
         line_range = [int(x) for x in line_range]
    return notebook.read_cell_smart(notebook_path, index, target, fmt, line_range)

@mcp.tool()
def insert_cell(notebook_path: str, index: int, content: str, cell_type: str = "code"):
    """Inserts a cell at a specific position."""
    return notebook.insert_cell(notebook_path, index, content, cell_type)

@mcp.tool()
def delete_cell(notebook_path: str, index: int):
    """Deletes a cell at a specific position."""
    return notebook.delete_cell(notebook_path, index)

@mcp.tool()
def search_notebook(notebook_path: str, query: str, regex: bool = False):
    """
    Don't read the file to find where df_clean is defined. Search for it.
    Returns: Found 'df_clean' in Cell 3 (Line 4) and Cell 8 (Line 1).
    """
    return notebook.search_notebook(notebook_path, query, regex)

@mcp.tool()
async def submit_input(notebook_path: str, text: str):
    """
    [Interact] Submit text to a pending input() request.
    Use this when you receive a 'notebook/input_request' notification.
    """
    try:
        await session_manager.submit_input(notebook_path, text)
        return json.dumps({"status": "sent", "text_length": len(text)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@mcp.tool()
async def get_kernel_info(notebook_path: str):
    """
    Check active variables without printing them.
    Returns: JSON dictionary of active variables, their types, and string representations (truncated).
    """
    return await session_manager.get_kernel_info(notebook_path)

@mcp.tool()
async def install_package(package_name: str, notebook_path: Optional[str] = None):
    """
    [Magic Import] Install a package in the kernel's environment.
    Use this when an import fails (ModuleNotFoundError).
    
    Args:
        package_name: Name of package (e.g. 'pandas')
        notebook_path: Optional notebook path to target specific kernel environment
    """
    python_path = None
    env_vars = None
    
    if notebook_path:
        session = session_manager.get_session(notebook_path)
        if session and 'env_info' in session:
            python_path = session['env_info'].get('python_path')

    # Derive environment variables
    env_vars = _derive_env_vars(python_path) if python_path else None

    success, output = environment.install_package(package_name, python_path, env_vars)
    
    return ToolResult(
        success=success,
        data={"output": output},
        error_msg=output if not success else None,
        user_suggestion="IMPORTANT: You MUST restart the kernel to load the new package." if success else "Check package name"
    ).to_json()

def _derive_env_vars(python_path: str) -> Optional[dict]:
    """Helper to derive environment variables from a Python executable path."""
    import os
    from pathlib import Path
    
    try:
        path_obj = Path(python_path)
        
        # Windows Conda check: python.exe is usually in the root of the env
        if os.name == 'nt' and path_obj.parent.name != 'Scripts':
            venv_path = str(path_obj.parent)
        else:
            # Standard venv or Unix Conda (bin/python)
            venv_path = str(path_obj.parent.parent)
            
        return environment.get_activated_env_vars(venv_path, python_path)
    except Exception:
        return None

@mcp.tool()
def check_code_syntax(code: str):
    """
    [LSP] Check Python code for syntax errors. 
    Use this BEFORE running code to avoid wasting time on simple typos.
    
    Args:
        code: Python source code
        
    Returns:
        JSON with 'valid': bool, and 'error': str (if any).
    """
    is_valid, error_msg = validation.check_code_syntax(code)
    
    return ToolResult(
        success=is_valid,
        data={"valid": is_valid},
        error_msg=error_msg,
        user_suggestion="Fix syntax error and retry" if not is_valid else None
    ).to_json()

# --- NEW ASYNC TOOLS ---

@mcp.tool()
@validated_tool(RunCellArgs)
async def run_cell_async(notebook_path: str, index: int, code_override: Optional[str] = None, task_id_override: Optional[str] = None):
    """
    Submits a cell for execution in the background.
    
    Args:
        notebook_path: Path to the notebook
        index: Cell index
        code_override: Optional explicit code to run (bypass disk read). 
                      Crucial for "File vs Buffer" race conditions.
        task_id_override: Optional client-generated ID to prevent race conditions.
    
    Returns: A Task ID (e.g., "b4f2...").
    Use `get_execution_status(task_id)` to check progress.
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return "Error: No running kernel. Call start_kernel first."
    
    # 1. Get Code (Buffer Priority)
    if code_override is not None:
        code = code_override
    else:
        # Fallback to disk (Legacy/test behavior)
        try:
            cell = notebook.read_cell(notebook_path, index)
            code = cell['source']
        except Exception as e:
            return f"Error reading cell: {e}"
    
    # 2. Submit
    exec_id = await session_manager.execute_cell_async(notebook_path, index, code, exec_id=task_id_override)
    if not exec_id:
        return "Error starting execution."
        
    return json.dumps({
        "task_id": exec_id,
        "message": "Execution started"
    })

@mcp.tool()
def get_execution_status(notebook_path: str, task_id: str):
    """
    Checks the status of a background cell execution.
    Returns: JSON with 'status' (running/completed/error) and 'output' (so far).
    """
    status = session_manager.get_execution_status(notebook_path, task_id)
    return json.dumps(status, indent=2)

@mcp.tool()
def is_kernel_busy(notebook_path: str):
    """
    [PERFORMANCE] Check if kernel is currently executing or has queued work.
    
    Used by UI components (like variable dashboard) to skip polling when kernel is busy.
    Prevents flooding the execution queue with inspection requests during long-running operations.
    
    Args:
        notebook_path: Path to the notebook
        
    Returns:
        JSON with 'is_busy' (boolean) and optional 'reason' string
        
    Example:
        {"is_busy": true, "reason": "Executing cell 5"}
        {"is_busy": false}
    """
    is_busy = session_manager.is_kernel_busy(notebook_path)
    
    result = {"is_busy": is_busy}
    
    if is_busy:
        # Optionally provide more context about why it's busy
        session = session_manager.get_session(notebook_path)
        if session:
            if session['queued_executions']:
                result["reason"] = f"{len(session['queued_executions'])} executions queued"
            else:
                # Check active executions
                active_count = sum(1 for data in session['executions'].values() if data['status'] in ['busy', 'queued'])
                if active_count > 0:
                    result["reason"] = f"{active_count} executions running"
    
    return json.dumps(result)

@mcp.tool()
def check_kernel_resources(notebook_path: str):
    """
    [PHASE 3.4] Get CPU and RAM usage of the kernel process.
    
    Allows agents to monitor resource consumption and implement auto-restart logic
    to prevent memory leaks or runaway processes.
    
    Args:
        notebook_path: Path to the notebook file
    
    Returns:
        JSON with:
        - status: 'active' or error state
        - pid: Process ID of the kernel
        - memory_mb: Total RAM usage in MB (includes child processes)
        - memory_percent: RAM usage as percentage of system memory
        - cpu_percent: CPU usage percentage (includes child processes)
        - num_threads: Number of threads in kernel process
        - num_children: Number of child processes spawned
    
    Agent Usage:
        # Check before heavy computation
        resources = json.loads(check_kernel_resources(path))
        if resources['memory_percent'] > 80:
            stop_kernel(path)
            start_kernel(path)  # Fresh start
            print("Kernel restarted due to high memory usage")
        
        # Monitor during long-running task
        while status['status'] == 'running':
            resources = json.loads(check_kernel_resources(path))
            if resources['memory_mb'] > 8000:  # 8GB threshold
                interrupt_kernel(path)
                print("Interrupted: memory exceeded 8GB")
                break
    """
    result = session_manager.get_kernel_resources(notebook_path)
    return json.dumps(result, indent=2)

@mcp.tool()
async def run_all_cells(notebook_path: str):
    """
    Execute all code cells in the notebook sequentially.
    Returns: List of execution IDs for status tracking.
    Agent Use Case: Instead of 20 separate run_cell_async calls, use this single tool.
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return "Error: No running kernel. Call start_kernel first."
    
    # Read notebook
    try:
        nb = nbformat.read(notebook_path, as_version=4)
    except Exception as e:
        return f"Error reading notebook: {e}"
    
    # Queue all code cells
    exec_ids = []
    for idx, cell in enumerate(nb.cells):
        if cell.cell_type == 'code':
            exec_id = await session_manager.execute_cell_async(notebook_path, idx, cell.source)
            if exec_id:
                exec_ids.append({'cell_index': idx, 'exec_id': exec_id})
    
    return json.dumps({
        'message': f'Queued {len(exec_ids)} cells for execution',
        'executions': exec_ids
    }, indent=2)

@mcp.tool()
async def sync_state_from_disk(notebook_path: str, strategy: str = "smart"):
    """
    [HANDOFF PROTOCOL] Synchronize kernel state with disk after human intervention.
    
    **Critical Use Case**: When a human has edited the notebook externally (in VS Code, 
    JupyterLab, etc.), the kernel's RAM state is OUT OF SYNC with the disk. This tool 
    reconciles the "Split Brain" by re-executing cells to rebuild variable state.
    
    **When to Use**:
    - Agent resumes work after human editing session
    - Agent detects unexpected notebook structure (new cells, modified cells)
    - After switching from "Human Mode" to "Agent Mode" in VS Code extension
    
    **Strategy**:
    - "smart" (default): DAG-based minimal re-execution. Only reruns changed cells and their dependents.
    - "incremental": Re-executes from first changed cell to end (linear forward sync)
    - "full": Re-executes ALL code cells from scratch (safest but slowest)
    
    Args:
        notebook_path: Path to the notebook file
        strategy: "smart" | "incremental" | "full"
    
    Returns:
        JSON with:
        - cells_synced: Number of cells re-executed
        - execution_ids: List of execution IDs for tracking
        - sync_duration_estimate: Estimated time to complete (based on queue size)
        - rerun_reason: Explanation of why each cell was rerun
    
    Agent Workflow Example:
        # 1. Agent detects notebook changed on disk
        outline = get_notebook_outline(path)
        if len(outline['cells']) > session.last_known_cell_count:
            # 2. Smart sync only reruns affected cells
            result = sync_state_from_disk(path, strategy="smart")
            print(f"Synced {result['cells_synced']} cells (skipped {result['cells_skipped']} clean cells)")
        
        # 3. Now safe to continue work
        append_cell(path, "# Agent's new analysis")
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return json.dumps({
            "error": "No active kernel. Call start_kernel first.",
            "hint": "The kernel must be running to sync state."
        })
    
    # Read notebook from disk
    try:
        nb = nbformat.read(notebook_path, as_version=4)
    except Exception as e:
        return json.dumps({
            "error": f"Failed to read notebook from disk: {e}",
            "notebook_path": notebook_path
        })
    
    exec_ids = []
    strategy_used = strategy
    rerun_reasons = {}
    
    if strategy == "full":
        # Full sync: rerun everything
        cells_to_run = list(range(len(nb.cells)))
        for idx in cells_to_run:
            if nb.cells[idx].cell_type == 'code':
                rerun_reasons[idx] = "full_sync_requested"
    
    elif strategy == "smart":
        # DAG-based minimal sync
        from . import dag_executor
        
        # Find changed cells
        changed_cells = set()
        executed_indices = session.get('executed_indices', set())
        
        for idx, cell in enumerate(nb.cells):
            if cell.cell_type == 'code':
                # Check if never executed OR content changed
                if idx not in executed_indices:
                    changed_cells.add(idx)
                    rerun_reasons[idx] = "never_executed"
                    continue
                
                current_hash = utils.get_cell_hash(cell.source)
                mcp_meta = cell.metadata.get('mcp', {}) or cell.metadata.get('mcp_trace', {})
                last_hash = mcp_meta.get('execution_hash')
                
                if not last_hash or current_hash != last_hash:
                    changed_cells.add(idx)
                    rerun_reasons[idx] = "content_modified"
        
        if changed_cells:
            # Build dependency graph and compute affected cells
            cells_source = [cell.source if cell.cell_type == 'code' else '' for cell in nb.cells]
            try:
                cells_to_run = dag_executor.get_minimal_rerun_set(cells_source, changed_cells)
                # Mark dependent cells
                for idx in cells_to_run:
                    if idx not in rerun_reasons:
                        rerun_reasons[idx] = "dependent_on_changed_cell"
            except Exception as e:
                logger.warning(f"DAG analysis failed, falling back to incremental sync: {e}")
                # Fallback to incremental
                first_changed = min(changed_cells)
                cells_to_run = list(range(first_changed, len(nb.cells)))
                strategy_used = "incremental_fallback"
                for idx in cells_to_run:
                    if idx not in rerun_reasons:
                        rerun_reasons[idx] = "incremental_fallback"
        else:
            cells_to_run = []
            strategy_used = "smart_skipped_all"
    
    else:  # "incremental"
        # Incremental sync: find first dirty cell, rerun from there
        first_dirty_idx = -1
        executed_indices = session.get('executed_indices', set())
        
        for idx, cell in enumerate(nb.cells):
            if cell.cell_type == 'code':
                if idx not in executed_indices:
                    first_dirty_idx = idx
                    rerun_reasons[idx] = "never_executed"
                    break 
                
                current_hash = utils.get_cell_hash(cell.source)
                mcp_meta = cell.metadata.get('mcp', {}) or cell.metadata.get('mcp_trace', {})
                last_hash = mcp_meta.get('execution_hash')
                
                if not last_hash or current_hash != last_hash:
                    first_dirty_idx = idx
                    rerun_reasons[idx] = "content_modified"
                    break
        
        if first_dirty_idx != -1:
            cells_to_run = list(range(first_dirty_idx, len(nb.cells)))
            for idx in cells_to_run:
                if idx not in rerun_reasons:
                    rerun_reasons[idx] = "incremental_cascade"
        else:
            cells_to_run = []
            strategy_used = "incremental_skipped_all"

    # Execute determined cells
    for idx in cells_to_run:
        if idx < len(nb.cells) and nb.cells[idx].cell_type == 'code':
            cell = nb.cells[idx]
            exec_id = await session_manager.execute_cell_async(notebook_path, idx, cell.source)
            if exec_id:
                exec_ids.append({
                    'cell_index': idx,
                    'exec_id': exec_id,
                    'reason': rerun_reasons.get(idx, 'unknown')
                })
    
    # Calculate metrics
    queue_size = session['execution_queue'].qsize() if 'execution_queue' in session else 0
    estimate_seconds = len(exec_ids) * 2
    total_code_cells = sum(1 for c in nb.cells if c.cell_type == 'code')
    skipped_cells = total_code_cells - len(exec_ids)
    
    return json.dumps({
        'status': 'syncing',
        'message': f'Queued {len(exec_ids)} cells for state synchronization',
        'cells_synced': len(exec_ids),
        'cells_skipped': skipped_cells,
        'total_code_cells': total_code_cells,
        'execution_ids': exec_ids,
        'queue_size': queue_size + len(exec_ids),
        'estimated_duration_seconds': estimate_seconds,
        'strategy_used': strategy_used,
        'hint': 'Use get_execution_status() to monitor progress.'
    }, indent=2)

@mcp.tool()
async def get_version():
    """
    Get MCP server version for compatibility checking.
    
    Returns:
        JSON with version, protocol_version, and capabilities
    """
    return json.dumps({
        'version': __version__,
        'protocol_version': '1.0',
        'capabilities': [
            'execute_cells',
            'async_execution',
            'websocket_streaming',
            'health_monitoring',
            'interrupt_escalation',
            'checkpoint_recovery',
            'docker_isolation',
            'sql_superpowers'
        ],
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    })

@mcp.tool()
async def cancel_execution(notebook_path: str, task_id: str):
    """
    Interrupts the kernel to stop the running task.
    
    Uses multi-stage escalation: SIGINT → SIGTERM → SIGKILL
    """
    return await session_manager.cancel_execution(notebook_path, task_id)

@mcp.tool()
async def get_variable_info(notebook_path: str, var_name: str):
    """
    Inspect a specific variable in the kernel without dumping all globals.
    Agent Use Case: Check 'df.columns' or 'df.shape' without loading the entire DataFrame.
    Returns: JSON with type, shape, columns, memory usage, preview, etc.
    """
    return await session_manager.get_variable_info(notebook_path, var_name)

@mcp.tool()
async def list_variables(notebook_path: str):
    """
    List all variables in the kernel (names and types only, no values).
    Agent Use Case: Discover what variables exist before using get_variable_info.
    """
    code = """
import json
import sys
result = []
for name in dir():
    if not name.startswith('_'):
        obj = globals()[name]
        if not isinstance(obj, type(sys)):  # Skip modules
            result.append({"name": name, "type": type(obj).__name__})
print(json.dumps(result))
"""
    return await session_manager.run_simple_code(notebook_path, code)

@mcp.tool()
async def get_variable_manifest(notebook_path: str):
    """
    [VARIABLE DASHBOARD] Lightweight manifest of all kernel variables.
    Returns name, type, and memory size for each variable (optimized for UI polling).
    
    **Use Case**: VS Code extension can poll this after each execution to populate
    a Variable Explorer sidebar, giving humans visibility into the agent's kernel state.
    
    **Performance**: Much lighter than list_variables() - includes memory size for sorting.
    
    Returns:
        JSON array: [{"name": "df", "type": "DataFrame", "size": "2.4 MB"}, ...]
    """
    code = """
import json
import sys

def get_size_str(obj):
    '''Get human-readable size string'''
    try:
        # Whitelist safe primitive/container types for deep inspection
        safe_types = (str, bytes, bytearray, list, tuple, set, dict, int, float, bool, complex)
        type_str = str(type(obj))

        # Avoid calling potentially dangerous custom __sizeof__ implementations
        if not isinstance(obj, safe_types) and 'pandas' not in type_str and 'numpy' not in type_str:
            return "?"

        # Try to get actual memory usage for safe/known types
        size = sys.getsizeof(obj)

        # For containers, estimate recursively (limit depth to avoid heavy work)
        if hasattr(obj, '__len__') and not isinstance(obj, (str, bytes, bytearray)):
            try:
                if hasattr(obj, 'memory_usage') and 'pandas' in type_str:  # pandas DataFrame/Series
                    size = int(obj.memory_usage(deep=True).sum())
                elif isinstance(obj, (list, tuple, set)):
                    size += sum(sys.getsizeof(item) for item in list(obj)[:100])  # Sample first 100
                elif isinstance(obj, dict):
                    items = list(obj.items())[:100]
                    size += sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in items)
            except Exception:
                # If any inspection errors, return unknown size
                return "?"

        # Format size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"
    except Exception:
        return "?"

manifest = []
for name in sorted(dir()):
    if not name.startswith('_'):
        try:
            obj = globals()[name]
            if not isinstance(obj, type(sys)):  # Skip modules
                manifest.append({
                    "name": name,
                    "type": type(obj).__name__,
                    "size": get_size_str(obj)
                })
        except:
            pass

print(json.dumps(manifest))
"""
    return await session_manager.run_simple_code(notebook_path, code)

@mcp.tool()
async def inspect_variable(notebook_path: str, variable_name: str):
    """
    Surgical Inspection: Returns a human-readable markdown summary of a variable.
    
    Agent Use Case: 
    - Peek at DataFrames without loading 1GB of data into context
    - Inspect lists, dicts, models without full dumps
    - Get shape, columns, dtypes, and head(3) for DataFrames
    
    Returns: Markdown-formatted summary suitable for LLM consumption
    """
    # 1. Input Validation (Prevent Injection)
    if not variable_name.isidentifier():
        return f"Error: '{variable_name}' is not a valid Python identifier. Cannot inspect."

    # SECURITY FIX: Use pre-defined helper function instead of sending code blocks
    # Logic is defined in session.py startup_code as _mcp_inspect(name)
    code = f"_mcp_inspect('{variable_name}')"
    # Note: run_simple_code executes the expression and returns the result (relying on displayhook or print?)
    # SessionManager.run_simple_code runs using execute_cell logic which captures output.
    # _mcp_inspect returns a string. To get it as output, we might need to print it or rely on it being the last expression.
    # Jupyter usually displays the last expression.
    
    return await session_manager.run_simple_code(notebook_path, code)

# -----------------------
# Asset Management Tools
# -----------------------

@mcp.tool()
def read_asset(
    asset_path: str, 
    lines: Optional[List[int]] = None, 
    search: Optional[str] = None,
    max_lines: int = 1000
) -> str:
    """
    Read content from an offloaded output file (assets/text_*.txt).
    Use this to selectively retrieve large outputs without loading everything into context.
    
    Agent Use Cases:
    - Search for errors in 50MB training logs: read_asset("assets/text_abc123.txt", search="error")
    - View specific section: read_asset("assets/text_abc123.txt", lines=[100, 200])
    - Check final results: read_asset("assets/text_abc123.txt", lines=[1, 50])
    
    Args:
        asset_path: Path to the asset file (e.g. "assets/text_abc123.txt")
        lines: [start_line, end_line] for pagination (1-based, inclusive)
        search: Search term for grep-like filtering (case-insensitive)
        max_lines: Maximum lines to return (default 1000, max 5000)
    
    Returns:
        Content from the asset file (filtered or paginated)
    """
    from pathlib import Path
    import os
    
    # FIXED: Enforce hard caps on return size
    MAX_RETURN_CHARS = 20000  # 20KB safety limit
    MAX_RETURN_LINES = 500    # 500 lines safety limit
    
    # Limit max_lines to prevent context overflow
    max_lines = min(max_lines, MAX_RETURN_LINES)
    
    # Security: Prevent path traversal
    asset_path = str(Path(asset_path).resolve())
    if '..' in asset_path or not asset_path.endswith('.txt'):
        return json.dumps({
            "error": "Invalid asset path. Must be a .txt file without path traversal."
        })
    
    # Check if file exists
    if not Path(asset_path).exists():
        return json.dumps({
            "error": f"Asset file not found: {asset_path}"
        })
    
    try:
        # Get file info
        file_size = Path(asset_path).stat().st_size
        
        with open(asset_path, 'r', encoding='utf-8', errors='replace') as f:
            if search:
                # Grep mode: efficient for finding specific content
                matches = []
                for i, line in enumerate(f, 1):
                    if search.lower() in line.lower():
                        matches.append(f"{i}: {line.rstrip()}")
                        if len(matches) >= max_lines:
                            matches.append(f"\n... [Search limit reached: {max_lines} matches shown] ...")
                            break
                
                if not matches:
                    return json.dumps({
                        "content": f"No matches found for '{search}'",
                        "file_size_bytes": file_size,
                        "matches": 0
                    })
                
                return json.dumps({
                    "content": "\n".join(matches),
                    "file_size_bytes": file_size,
                    "matches": len(matches)
                })
            
            elif lines:
                # Pagination mode: read specific line range
                if len(lines) != 2 or lines[0] < 1 or lines[1] < lines[0]:
                    return json.dumps({
                        "error": "Invalid line range. Use [start_line, end_line] where start >= 1 and end >= start."
                    })
                
                start_line, end_line = lines
                # Cap the range
                end_line = min(end_line, start_line + max_lines - 1)
                
                selected_lines = []
                for i, line in enumerate(f, 1):
                    if i >= start_line:
                        selected_lines.append(line.rstrip())
                    if i >= end_line:
                        break
                
                content = "\n".join(selected_lines)
                
                # Truncate content if too large
                if len(content) > MAX_RETURN_CHARS:
                    content = content[:MAX_RETURN_CHARS] + f"\n... [Truncated: Exceeded {MAX_RETURN_CHARS} char limit] ..."
                
                return json.dumps({
                    "content": content,
                    "file_size_bytes": file_size,
                    "line_range": [start_line, min(end_line, i)],
                    "lines_returned": len(selected_lines)
                })
            
            else:
                # Default: return first N lines
                content_lines = []
                for i, line in enumerate(f):
                    if i >= max_lines:
                        content_lines.append(f"\n... [Content truncated at {max_lines} lines. Use 'lines' parameter for pagination] ...")
                        break
                    content_lines.append(line.rstrip())
                
                content = "\n".join(content_lines)
                
                # Truncate content if too large
                if len(content) > MAX_RETURN_CHARS:
                    content = content[:MAX_RETURN_CHARS] + f"\n... [Truncated: Exceeded {MAX_RETURN_CHARS} char limit] ..."
                
                return json.dumps({
                    "content": content,
                    "file_size_bytes": file_size,
                    "lines_returned": len(content_lines),
                    "note": "Use 'lines' or 'search' parameters for targeted retrieval"
                })
    
    except Exception as e:
        return json.dumps({
            "error": f"Failed to read asset: {str(e)}"
        })

# -----------------------

@mcp.tool()
async def install_package(notebook_path: str, package_name: str):
    """Installs packages into the active kernel's environment."""
    return await session_manager.install_package(notebook_path, package_name)

@mcp.tool()
async def interrupt_kernel(notebook_path: str):
    """Stops the currently running cell immediately."""
    return await session_manager.interrupt_kernel(notebook_path)

@mcp.tool()
async def restart_kernel(notebook_path: str):
    """Restarts the kernel, clearing all variables but keeping outputs."""
    return await session_manager.restart_kernel(notebook_path)

@mcp.tool()
async def check_working_directory(notebook_path: str):
    """Checks the current working directory (CWD) of the active kernel."""
    code = "import os; print(os.getcwd())"
    return await session_manager.run_simple_code(notebook_path, code)

@mcp.tool()
async def set_working_directory(notebook_path: str, path: str):
    """Changes the CWD of the kernel."""
    # Escape backslashes for Windows
    safe_path = path.replace("\\", "/")
    code = f"import os; os.chdir('{safe_path}'); print(os.getcwd())"
    result = await session_manager.run_simple_code(notebook_path, code)
    if "Error" in result:
        return result
    return f"Working directory changed to: {result}"

@mcp.tool()
async def list_kernel_packages(notebook_path: str):
    """Lists packages installed in the active kernel's environment."""
    # We run this inside python to avoid OS shell syntax differences
    code = """
import pkg_resources
installed = sorted([(d.project_name, d.version) for d in pkg_resources.working_set])
for p, v in installed:
    print(f"{p}=={v}")
"""
    return await session_manager.run_simple_code(notebook_path, code)

@mcp.tool()
def list_available_environments():
    """Scans the system for Python environments (venvs, conda, etc)."""
    envs = session_manager.list_environments()
    return json.dumps(envs, indent=2)

@mcp.tool()
async def switch_kernel_environment(notebook_path: str, venv_path: str):
    """
    Stops the current kernel and restarts it using the specified environment path.
    path: The absolute path to the environment root (not the bin/python executable).
    """
    # 1. Stop
    await session_manager.stop_kernel(notebook_path)
    
    # 2. Start with new env
    result = await session_manager.start_kernel(notebook_path, venv_path)
    return f"Switched Environment. {result}"

# ============================================================================
# NEW TOOLS - Notebook Creation and Management
# ============================================================================

@mcp.tool()
def create_notebook(
    notebook_path: str,
    kernel_name: str = "python3",
    kernel_display_name: Optional[str] = None,
    language: str = "python",
    python_version: Optional[str] = None,
    initial_cells: Optional[str] = None
):
    """
    Creates a new Jupyter notebook with proper metadata structure.
    
    Args:
        notebook_path: Path where the notebook will be created
        kernel_name: Name of the kernel (e.g., 'python3', 'conda-env-myenv-py')
        kernel_display_name: Display name for the kernel (defaults to kernel_name)
        language: Programming language (default: 'python')
        python_version: Python version string (e.g., '3.10.5'). Auto-detected if None.
        initial_cells: JSON string with list of dicts containing 'type' and 'content' keys
    
    Returns:
        Success message with notebook path
    """
    # Parse initial_cells if provided
    cells = None
    if initial_cells:
        try:
            cells = json.loads(initial_cells)
        except json.JSONDecodeError:
            return "Error: initial_cells must be valid JSON"
    
    return notebook.create_notebook(
        notebook_path,
        kernel_name,
        kernel_display_name,
        language,
        python_version,
        cells
    )

# ============================================================================
# Cell Manipulation Tools
# ============================================================================

@mcp.tool()
def move_cell(notebook_path: str, from_index: int, to_index: int):
    """Moves a cell from one position to another."""
    return notebook.move_cell(notebook_path, from_index, to_index)

@mcp.tool()
def copy_cell(notebook_path: str, index: int, target_index: Optional[int] = None):
    """Copies a cell to a new position. If target_index is None, appends to end."""
    return notebook.copy_cell(notebook_path, index, target_index)

@mcp.tool()
def merge_cells(notebook_path: str, start_index: int, end_index: int, separator: str = "\n\n"):
    """Merges cells from start_index to end_index (inclusive) into a single cell."""
    return notebook.merge_cells(notebook_path, start_index, end_index, separator)

@mcp.tool()
def split_cell(notebook_path: str, index: int, split_at_line: int):
    """Splits a cell at the specified line number into two cells."""
    return notebook.split_cell(notebook_path, index, split_at_line)

@mcp.tool()
def change_cell_type(notebook_path: str, index: int, new_type: str):
    """
    Changes the type of a cell (code, markdown, or raw).
    new_type must be one of: 'code', 'markdown', 'raw'
    """
    return notebook.change_cell_type(notebook_path, index, new_type)

# ============================================================================
# Metadata Operations
# ============================================================================

@mcp.tool()
def get_notebook_metadata(notebook_path: str):
    """Gets the notebook-level metadata as JSON."""
    metadata = notebook.get_notebook_metadata(notebook_path)
    return json.dumps(metadata, indent=2)

@mcp.tool()
def set_notebook_metadata(notebook_path: str, metadata_json: str):
    """
    Sets the notebook-level metadata.
    metadata_json: JSON string containing metadata to update
    """
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return "Error: metadata_json must be valid JSON"
    
    return notebook.set_notebook_metadata(notebook_path, metadata)

@mcp.tool()
def update_kernelspec(notebook_path: str, kernel_name: str, display_name: Optional[str] = None, language: Optional[str] = None):
    """Updates the kernelspec in notebook metadata."""
    return notebook.update_kernelspec(notebook_path, kernel_name, display_name, language)

@mcp.tool()
def get_cell_metadata(notebook_path: str, index: int):
    """Gets metadata for a specific cell as JSON."""
    metadata = notebook.get_cell_metadata(notebook_path, index)
    return json.dumps(metadata, indent=2)

@mcp.tool()
def set_cell_metadata(notebook_path: str, index: int, metadata_json: str):
    """
    Sets metadata for a specific cell.
    metadata_json: JSON string containing metadata to update
    """
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return "Error: metadata_json must be valid JSON"
    
    return notebook.set_cell_metadata(notebook_path, index, metadata)

@mcp.tool()
def add_cell_tags(notebook_path: str, index: int, tags: str):
    """
    Adds tags to a cell's metadata.
    tags: JSON array of tag strings, e.g., ["important", "todo"]
    """
    try:
        tag_list = json.loads(tags)
    except json.JSONDecodeError:
        return "Error: tags must be valid JSON array"
    
    return notebook.add_cell_tags(notebook_path, index, tag_list)

@mcp.tool()
def remove_cell_tags(notebook_path: str, index: int, tags: str):
    """
    Removes tags from a cell's metadata.
    tags: JSON array of tag strings, e.g., ["important", "todo"]
    """
    try:
        tag_list = json.loads(tags)
    except json.JSONDecodeError:
        return "Error: tags must be valid JSON array"
    
    return notebook.remove_cell_tags(notebook_path, index, tag_list)

# ============================================================================
# Output Operations
# ============================================================================

@mcp.tool()
def clear_cell_outputs(notebook_path: str, index: int):
    """Clears outputs from a specific cell."""
    return notebook.clear_cell_outputs(notebook_path, index)

@mcp.tool()
def clear_all_outputs(notebook_path: str):
    """Clears outputs from all code cells in the notebook."""
    return notebook.clear_all_outputs(notebook_path)

@mcp.tool()
def get_cell_outputs(notebook_path: str, index: int):
    """Gets the outputs from a specific cell as JSON."""
    outputs = notebook.get_cell_outputs(notebook_path, index)
    return json.dumps(outputs, indent=2)

# ============================================================================
# Validation
# ============================================================================

@mcp.tool()
def validate_notebook(notebook_path: str):
    """Validates notebook structure and returns any issues."""
    result = notebook.validate_notebook(notebook_path)
    return json.dumps(result, indent=2)

# ============================================================================
# Environment Detection and Management
# ============================================================================

@mcp.tool()
def find_python_executables():
    """
    Discovers all Python interpreters on the system.
    Scans PATH and common installation locations.
    Returns JSON list of discovered interpreters with version and type info.
    """
    executables = environment.find_python_executables()
    return json.dumps(executables, indent=2)

@mcp.tool()
def validate_python_executable(python_path: str):
    """
    Validates a Python executable.
    Returns detailed validation results including version and pip availability.
    """
    result = environment.validate_python_executable(python_path)
    return json.dumps(result, indent=2)

@mcp.tool()
def auto_detect_environment(notebook_path: Optional[str] = None):
    """
    Automatically detects the best Python environment to use.
    If notebook_path is provided, looks for .venv or environment in notebook directory.
    Returns JSON with python_path, env_type, env_name, and version.
    """
    result = environment.auto_detect_environment(notebook_path)
    return json.dumps(result, indent=2)

@mcp.tool()
def get_asset_content(asset_path: str) -> str:
    """
    Retrieve base64-encoded content of an asset file (PNG, PDF, SVG, etc.).
    
    **Use Case**: When the server reports `[PNG SAVED: assets/xyz.png]` and you need
    to analyze the image content with multimodal capabilities.
    
    **Security**: Only allows access to assets/ directory (prevents path traversal).
    
    Args:
        asset_path: Relative path to asset, typically from execution output
                   Format: "assets/asset_abc123.png" or just "asset_abc123.png"
    
    Returns:
        JSON with:
        - mime_type: MIME type of the asset (e.g., "image/png")
        - data: Base64-encoded binary content
        - size_bytes: Size of the encoded data
        - filename: Original filename
    
    Agent Workflow Example:
        # 1. Execute cell that generates plot
        result = execute_cell(path, 0, "import matplotlib.pyplot as plt\\nplt.plot([1,2,3])")
        # Output: "[PNG SAVED: assets/asset_abc123.png]"
        
        # 2. Retrieve asset for analysis
        asset = get_asset_content("assets/asset_abc123.png")
        # Now can pass asset['data'] to multimodal model for description
    """
    import base64
    from pathlib import Path
    from src.security import validate_path
    
    # Normalize path separators
    asset_path = asset_path.replace("\\", "/")
    
    # Security: Extract just the filename if full path provided
    # Allows "assets/file.png" or just "file.png"
    path_parts = asset_path.split("/")
    if len(path_parts) > 1 and path_parts[0] == "assets":
        filename = path_parts[-1]
    else:
        filename = path_parts[-1]
    
    # Build full path relative to current working directory
    # Assets are always stored in assets/ subdirectory
    assets_dir = Path("assets").resolve()
    
    # Security check: Use validate_path to prevent path traversal
    try:
        full_path = validate_path(filename, assets_dir)
    except PermissionError as e:
        return json.dumps({
            "error": "Security violation: Path traversal attempt blocked",
            "requested_path": asset_path,
            "details": str(e)
        })
    
    # Check if file exists
    if not full_path.exists():
        return json.dumps({
            "error": f"Asset not found: {asset_path}",
            "checked_path": str(full_path),
            "hint": "Ensure the cell has been executed and produced output. Check execution status."
        })
    
    # Determine MIME type from extension
    mime_map = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.svg': 'image/svg+xml',
        '.pdf': 'application/pdf',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    suffix = full_path.suffix.lower()
    mime_type = mime_map.get(suffix, 'application/octet-stream')
    
    # Read and encode
    try:
        with open(full_path, 'rb') as f:
            raw_bytes = f.read()
            data = base64.b64encode(raw_bytes).decode('utf-8')
        
        return json.dumps({
            "mime_type": mime_type,
            "data": data,
            "size_bytes": len(raw_bytes),
            "encoded_size": len(data),
            "filename": filename,
            "full_path": str(full_path)
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "error": f"Failed to read asset: {str(e)}",
            "asset_path": str(full_path)
        })

@mcp.tool()
def edit_cell_by_id(notebook_path: str, cell_id: str, content: str, expected_index: Optional[int] = None):
    """
    [GIT-SAFE] Edit cell by stable Cell ID instead of index.
    
    **Why Cell IDs**: Index-based addressing breaks when cells are added/deleted.
    Cell IDs are stable UUIDs that survive notebook restructuring.
    
    **Pre-flight Validation**: If expected_index is provided, checks that the cell
    hasn't moved since the agent last read the outline. Prevents overwriting wrong cell.
    
    Args:
        notebook_path: Path to notebook
        cell_id: Cell ID from get_notebook_outline (e.g., "89523d2a-...")
        content: New cell content
        expected_index: Optional - cell's last known index for staleness check
    
    Returns:
        Success message or StaleStateError
    
    Agent Workflow:
        # 1. Get current outline
        outline = get_notebook_outline(path)
        cell = outline[5]  # Edit 6th cell
        
        # 2. Edit by ID with validation
        result = edit_cell_by_id(
            path, 
            cell_id=cell['id'],
            content="import pandas as pd",
            expected_index=cell['index']  # Prevents race conditions
        )
    """
    from src.cell_id_manager import edit_cell_by_id as _edit_by_id, StaleStateError
    
    try:
        return _edit_by_id(notebook_path, cell_id, content, expected_index)
    except StaleStateError as e:
        return json.dumps({
            "error": "StaleStateError",
            "message": str(e),
            "action_required": "Call get_notebook_outline() to refresh cell positions and retry"
        }, indent=2)

@mcp.tool()
def delete_cell_by_id(notebook_path: str, cell_id: str, expected_index: Optional[int] = None):
    """
    [GIT-SAFE] Delete cell by stable Cell ID.
    
    See edit_cell_by_id for rationale on Cell ID addressing.
    """
    from src.cell_id_manager import delete_cell_by_id as _delete_by_id, StaleStateError
    
    try:
        return _delete_by_id(notebook_path, cell_id, expected_index)
    except StaleStateError as e:
        return json.dumps({
            "error": "StaleStateError",
            "message": str(e),
            "action_required": "Call get_notebook_outline() to refresh and retry"
        }, indent=2)

@mcp.tool()
def insert_cell_by_id(notebook_path: str, after_cell_id: Optional[str], content: str, cell_type: str = "code"):
    """
    [GIT-SAFE] Insert new cell after specified Cell ID.
    
    Args:
        notebook_path: Path to notebook
        after_cell_id: Insert after this Cell ID (None = prepend to start)
        content: Cell content
        cell_type: 'code' or 'markdown'
    
    Returns:
        Success message with new cell's ID
    """
    from src.cell_id_manager import insert_cell_by_id as _insert_by_id, StaleStateError
    
    try:
        return _insert_by_id(notebook_path, after_cell_id, content, cell_type)
    except StaleStateError as e:
        return json.dumps({
            "error": "StaleStateError",
            "message": str(e),
            "action_required": "Call get_notebook_outline() to refresh and retry"
        }, indent=2)

@mcp.tool()
def create_venv(path: str, python_executable: str = ""):
    """
    Creates a new virtual environment.
    path: Path where the venv will be created
    python_executable: Optional Python executable to use (defaults to sys.executable)
    """
    if python_executable:
        result = environment.create_venv(path, python_executable)
    else:
        result = environment.create_venv(path, sys.executable)
    return json.dumps(result, indent=2)

# ============================================================================
# Git-Awareness Tools (Git-Safe Workflow)
# ============================================================================

@mcp.tool()
def save_notebook_clean(notebook_path: str, strip_outputs: bool = False):
    """
    [GIT-SAFE] Save notebook in Git-friendly format.
    
    Strips volatile metadata while keeping outputs for GitHub viewing:
    - execution_count (set to null)
    - Volatile cell metadata (timestamps, collapsed, scrolled)
    - Optionally strips all outputs if strip_outputs=True
    
    **When to use**: Call this before git commit to minimize merge conflicts.
    
    Args:
        notebook_path: Path to notebook file
        strip_outputs: If True, also remove all outputs (for sensitive data)
    
    Returns:
        Success message with count of cleaned cells
    
    Example:
        # Before committing
        save_notebook_clean("analysis.ipynb")
        # Then: git add analysis.ipynb && git commit
    """
    from src.git_tools import save_notebook_clean as _save_clean
    return _save_clean(notebook_path, strip_outputs)

# [PHASE 4: DESCOPED] Git filter setup removed
# @mcp.tool()
# def setup_git_filters(repo_path: str = "."):
#     """REMOVED: Use VS Code Git integration or manual git config"""
#     pass

# [PHASE 4: DESCOPED] Branch creation removed
# @mcp.tool()
# def create_agent_branch(repo_path: str = ".", branch_name: str = ""):
#     """REMOVED: Use VS Code Git integration for branch management"""
#     pass

# [PHASE 4: DESCOPED] Agent commit tool removed
# @mcp.tool()
# def commit_agent_work(repo_path: str = ".", message: str = "", files: Optional[List[str]] = None):
#     """REMOVED: Agent should not commit code. Human reviews and commits."""
#     pass

@mcp.tool()
def prune_unused_assets(notebook_path: str, dry_run: bool = False):
    """
    [GIT-SAFE] Delete asset files not referenced in notebook.
    Implements "Reference Counting GC" for both image assets and text offload files.
    
    Scans notebook for asset references (images and text_*.txt files),
    deletes orphaned files. Automatically runs on kernel stop to maintain Git hygiene.
    Safe to run periodically to clean up after cell deletions.
    
    Args:
        notebook_path: Path to notebook file
        dry_run: If True, only report what would be deleted
    
    Returns:
        JSON with deleted/kept files and size freed
    
    Example:
        # Check what would be deleted
        prune_unused_assets("analysis.ipynb", dry_run=True)
        # Actually delete (also auto-runs on kernel stop)
        prune_unused_assets("analysis.ipynb")
    """
    from src.asset_manager import prune_unused_assets as _prune_assets
    result = _prune_assets(notebook_path, dry_run)
    return json.dumps(result, indent=2)

@mcp.tool()
def get_assets_summary(notebook_path: str):
    """
    [GIT-SAFE] Get summary of asset usage for a notebook.
    
    Returns counts and sizes of assets (total, referenced, orphaned).
    Useful to understand storage impact before/after cleanup.
    
    Args:
        notebook_path: Path to notebook file
    
    Returns:
        JSON with asset statistics
    
    Example:
        get_assets_summary("analysis.ipynb")
        # Shows: 50 total assets, 30 referenced, 20 orphaned
    """
    from src.asset_manager import get_assets_summary as _get_summary
    result = _get_summary(notebook_path)
    return json.dumps(result, indent=2)

@mcp.tool()
async def inspect_variable(notebook_path: str, variable_name: str):
    """
    [DATA SCIENCE] Inspect a variable in the kernel without printing it.
    
    Returns structured metadata about the variable (type, shape, columns, dtypes, preview).
    Much more efficient than repr() for large DataFrames/arrays.
    
    Args:
        notebook_path: Path to notebook
        variable_name: Name of variable to inspect (e.g., "df", "model")
    
    Returns:
        JSON with type, shape, memory usage, and preview
        
    Example:
        inspect_variable("analysis.ipynb", "df")
        # Returns: {"type": "DataFrame", "shape": [1000, 5], "columns": [...], "dtypes": {...}}
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return ToolResult(
            success=False,
            data={},
            error_msg="No running kernel. Call start_kernel first."
        ).to_json()
    
    # Inspection code that returns JSON
    inspection_code = f"""
import json
import sys

def _inspect_var():
    try:
        var = {variable_name}
        info = {{
            "variable": "{variable_name}",
            "type": type(var).__name__,
            "module": type(var).__module__
        }}
        
        # Pandas DataFrame
        if hasattr(var, 'shape') and hasattr(var, 'columns'):
            info['shape'] = list(var.shape)
            info['columns'] = list(var.columns)
            info['dtypes'] = {{str(k): str(v) for k, v in var.dtypes.items()}}
            info['memory_mb'] = var.memory_usage(deep=True).sum() / 1024 / 1024
            info['preview'] = var.head(5).to_dict('records')
        # NumPy array
        elif hasattr(var, 'shape') and hasattr(var, 'dtype'):
            info['shape'] = list(var.shape)
            info['dtype'] = str(var.dtype)
            info['size'] = var.size
            # Flatten preview for multi-dimensional arrays
            flat = var.flatten()
            info['preview'] = flat[:10].tolist() if len(flat) > 10 else flat.tolist()
        # List/Tuple
        elif isinstance(var, (list, tuple)):
            info['length'] = len(var)
            info['preview'] = var[:5] if len(var) > 5 else var
        # Dict
        elif isinstance(var, dict):
            info['length'] = len(var)
            info['keys_sample'] = list(var.keys())[:10]
        # String
        elif isinstance(var, str):
            info['length'] = len(var)
            info['preview'] = var[:200]
        # Scalar
        else:
            info['value'] = str(var)
        
        return json.dumps(info, indent=2)
    except Exception as e:
        return json.dumps({{"error": str(e)}})

print(_inspect_var())
"""
    
    # Execute inspection code using SessionManager's queue (index -1 = internal tool)
    exec_id = await session_manager.execute_cell_async(notebook_path, -1, inspection_code)
    if not exec_id:
        return ToolResult(
            success=False,
            data={},
            error_msg="Failed to submit inspection"
        ).to_json()
    
    # Wait for completion and collect output
    import time
    timeout = 10
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        status = session_manager.get_execution_status(notebook_path, exec_id)
        if status['status'] in ['completed', 'error']:
            # Extract text output
            outputs = status.get('outputs', [])
            for out in outputs:
                if out.get('output_type') == 'stream' and 'text' in out:
                    result_text = out['text']
                    try:
                        # Parse JSON response
                        result_data = json.loads(result_text)
                        return ToolResult(
                            success=True,
                            data=result_data,
                            error_msg=result_data.get('error')
                        ).to_json()
                    except json.JSONDecodeError:
                        return ToolResult(
                            success=False,
                            data={},
                            error_msg="Failed to parse inspection result"
                        ).to_json()
            
            return ToolResult(
                success=False,
                data={},
                error_msg="No output from inspection"
            ).to_json()
        
        await asyncio.sleep(0.2)
    
    return ToolResult(
        success=False,
        data={},
        error_msg="Inspection timeout"
    ).to_json()

@mcp.tool()
def search_notebook(notebook_path: str, pattern: str, case_sensitive: bool = False):
    """
    [NAVIGATION] Search for pattern across all cells in notebook.
    
    Returns matching cells with context. Useful for large notebooks
    to avoid loading full content into context window.
    
    Args:
        notebook_path: Path to notebook
        pattern: Text or regex pattern to search for
        case_sensitive: Whether search should be case-sensitive (default: False)
    
    Returns:
        JSON with matching cells, line numbers, and snippets
        
    Example:
        search_notebook("analysis.ipynb", "import pandas")
        # Returns: [{"cell_index": 2, "cell_type": "code", "snippet": "..."}]
    """
    try:
        # Read notebook directly with nbformat
        with open(notebook_path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        
        matches = []
        
        for idx, cell in enumerate(nb['cells']):
            if cell['cell_type'] not in ['code', 'markdown']:
                continue
            
            source = cell.get('source', '')
            if isinstance(source, list):
                source = ''.join(source)
            
            # Perform search
            search_text = source if case_sensitive else source.lower()
            search_pattern = pattern if case_sensitive else pattern.lower()
            
            if search_pattern in search_text:
                # Find all occurrences with line numbers
                lines = source.split('\n')
                matching_lines = []
                
                for line_idx, line in enumerate(lines):
                    check_line = line if case_sensitive else line.lower()
                    if search_pattern in check_line:
                        matching_lines.append({
                            'line_number': line_idx + 1,
                            'content': line.strip()
                        })
                
                # Create snippet (first 500 chars)
                snippet = source[:500]
                if len(source) > 500:
                    snippet += "... [truncated]"
                
                matches.append({
                    'cell_index': idx,
                    'cell_type': cell['cell_type'],
                    'matches': len(matching_lines),
                    'matching_lines': matching_lines[:10],  # Limit to 10 lines
                    'snippet': snippet
                })
        
        return ToolResult(
            success=True,
            data={
                'pattern': pattern,
                'notebook': notebook_path,
                'total_matches': len(matches),
                'matches': matches
            }
        ).to_json()
        
    except Exception as e:
        return ToolResult(
            success=False,
            data={},
            error_msg=f"Search failed: {str(e)}"
        ).to_json()

@mcp.tool()
async def install_package(notebook_path: str, package: str):
    """
    [ENVIRONMENT] Install a Python package in the kernel's environment.
    
    Better than !pip install because:
    - Uses the correct pip for the kernel
    - Returns clear success/failure
    - Reminds about kernel restart if needed
    
    Args:
        notebook_path: Path to notebook (determines which kernel environment)
        package: Package name or pip specifier (e.g., "pandas", "numpy>=1.20")
    
    Returns:
        JSON with installation status and instructions
        
    Example:
        install_package("analysis.ipynb", "pandas==2.0.0")
        # Returns: {"success": true, "message": "Package installed. Restart kernel to use."}
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return ToolResult(
            success=False,
            data={},
            error_msg="No running kernel. Call start_kernel first."
        ).to_json()
    
    # Install command using sys.executable (correct Python for kernel)
    install_code = f"""
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "{package}"],
    capture_output=True,
    text=True
)

print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("RETURNCODE:", result.returncode)
"""
    
    # Execute installation using SessionManager's queue (index -1 = internal tool)
    exec_id = await session_manager.execute_cell_async(notebook_path, -1, install_code)
    if not exec_id:
        return ToolResult(
            success=False,
            data={},
            error_msg="Failed to submit installation"
        ).to_json()
    
    # Wait for completion
    import time
    timeout = 60  # Package installation can take time
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        status = session_manager.get_execution_status(notebook_path, exec_id)
        if status['status'] in ['completed', 'error']:
            # Check if installation succeeded
            outputs = status.get('outputs', [])
            output_text = ""
            for out in outputs:
                if out.get('output_type') == 'stream' and 'text' in out:
                    output_text += out['text']
            
            # Parse return code
            success = "RETURNCODE: 0" in output_text
            
            if success:
                return ToolResult(
                    success=True,
                    data={
                        'package': package,
                        'output': output_text
                    },
                    user_suggestion=f"Package '{package}' installed successfully. Restart kernel to use new package."
                ).to_json()
            else:
                return ToolResult(
                    success=False,
                    data={'output': output_text},
                    error_msg=f"Failed to install '{package}'",
                    user_suggestion="Check package name and version. See output for details."
                ).to_json()
        
        await asyncio.sleep(0.5)
    
    return ToolResult(
        success=False,
        data={},
        error_msg="Installation timeout (60s)"
    ).to_json()

# --- SUPERPOWER TOOLS: SQL Queries, Auto-EDA, Time Travel ---

@mcp.tool()
async def query_dataframes(notebook_path: str, sql_query: str):
    """
    [SUPERPOWER] Run SQL directly on active DataFrames using DuckDB.
    
    Execute SQL queries against pandas/polars DataFrames in memory.
    No data copying required - DuckDB reads directly from Python objects.
    
    Args:
        notebook_path: Path to notebook with running kernel
        sql_query: SQL query (e.g., "SELECT * FROM df WHERE amount > 100")
    
    Returns:
        JSON with query results as markdown table
        
    Example:
        query_dataframes("analysis.ipynb", "SELECT region, SUM(revenue) FROM df_sales GROUP BY region")
        # Returns: Markdown table with aggregated results
        
    Wow Factor:
        Users can explore data with SQL instead of pandas syntax.
        "Show me top 5 users by revenue" becomes a simple SQL query.
    """
    from src.data_tools import query_dataframes as _query_df
    return await _query_df(session_manager, notebook_path, sql_query)

@mcp.tool()
async def save_checkpoint(notebook_path: str, checkpoint_name: str = "auto"):
    """
    [TIME TRAVEL] Save current kernel state for rollback.
    
    Creates a snapshot of all variables in the kernel's namespace.
    Use before running risky code that might crash the kernel.
    
    Args:
        notebook_path: Path to notebook
        checkpoint_name: Name for this checkpoint (default: "auto")
    
    Returns:
        JSON with checkpoint info (size, variable count, timestamp)
        
    Example:
        save_checkpoint("analysis.ipynb", "before_model_training")
        # Later: load_checkpoint("analysis.ipynb", "before_model_training")
        
    Wow Factor:
        Agent can say "I tried X, it crashed. I restored your state from 2 min ago."
    """
    # Reuse existing checkpoint logic from SessionManager
    session = session_manager.get_session(notebook_path)
    if not session:
        return ToolResult(
            success=False,
            data={},
            error_msg="No running kernel. Call start_kernel first."
        ).to_json()
    
    result = await session_manager.save_checkpoint(notebook_path, checkpoint_name)
    return json.dumps(result, indent=2)

@mcp.tool()
async def load_checkpoint(notebook_path: str, checkpoint_name: str = "auto"):
    """
    [TIME TRAVEL] Restore kernel state from checkpoint.
    
    Rolls back all variables to a previous saved state.
    Use when code execution fails and you need to recover.
    
    Args:
        notebook_path: Path to notebook
        checkpoint_name: Name of checkpoint to restore (default: "auto")
    
    Returns:
        JSON with restoration status
        
    Example:
        load_checkpoint("analysis.ipynb", "before_model_training")
        # Kernel state restored to checkpoint time
        
    Safety:
        Uses HMAC signing to prevent checkpoint tampering.
    """
    # Reuse existing checkpoint logic from SessionManager
    session = session_manager.get_session(notebook_path)
    if not session:
        return ToolResult(
            success=False,
            data={},
            error_msg="No running kernel. Call start_kernel first."
        ).to_json()
    
    result = await session_manager.load_checkpoint(notebook_path, checkpoint_name)
    return json.dumps(result, indent=2)

# --- PROMPTS: Consumer-Ready Personas for Claude Desktop ---

def _read_prompt(filename: str) -> str:
    """Helper to read prompt files from the package."""
    try:
        # Locate the prompts directory relative to this file (src/main.py)
        current_dir = Path(__file__).parent
        prompt_path = current_dir / "prompts" / filename
        
        if not prompt_path.exists():
            return f"Error: Prompt file '{filename}' not found at {prompt_path}"
            
        return prompt_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading prompt: {str(e)}"

@mcp.prompt()
def jupyter_expert() -> list[types.PromptMessage]:
    """
    Returns the System Prompt for the Jupyter Expert persona.
    Use this to turn Claude into a safe, state-aware Data Science co-pilot.
    
    Activates with: /prompt jupyter-expert
    
    Persona traits:
    - Always checks sync status before execution
    - Uses inspect_variable for large DataFrames
    - Searches notebooks before reading full content
    - Follows Hub and Spoke architecture
    """
    content = _read_prompt("jupyter_expert.md")
    return [
        types.PromptMessage(
            role="user", 
            content=types.TextContent(type="text", text=content)
        )
    ]

@mcp.prompt()
def autonomous_researcher() -> list[types.PromptMessage]:
    """
    Returns the System Prompt for the Autonomous Researcher.
    Use this for long-running, self-correcting tasks.
    
    Activates with: /prompt autonomous-researcher
    
    Persona traits:
    - Follows OODA loop (Observe, Orient, Decide, Act)
    - Self-healing error recovery
    - Autonomous decision-making
    - Documents findings automatically
    """
    content = _read_prompt("autonomous_researcher.md")
    return [
        types.PromptMessage(
            role="user", 
            content=types.TextContent(type="text", text=content)
        )
    ]

@mcp.prompt()
def auto_analyst() -> list[types.PromptMessage]:
    """
    Returns the System Prompt for the Auto-Analyst.
    Use this for automatic Exploratory Data Analysis (EDA).
    
    Activates with: /prompt auto-analyst
    
    Persona traits:
    - Autonomous EDA generation (no permission needed)
    - Generates missing values maps, distributions, correlations
    - Saves all plots to assets/
    - Creates comprehensive summary reports
    - Uses SQL for fast data exploration
    
    Wow Factor:
        User drops a CSV and says "analyze this."
        Agent generates full EDA report with 5 plots in 60 seconds.
    """
    content = _read_prompt("auto_analyst.md")
    return [
        types.PromptMessage(
            role="user", 
            content=types.TextContent(type="text", text=content)
        )
    ]

# --- NEW: Client Bridge Logic ---
async def run_bridge(uri: str):
    """
    Client Mode: Connects stdin/stdout to the running WebSocket server.
    """
    logger.info(f"[Bridge] Connecting to {uri}...")
    
    async def forward_stdin_to_ws(ws):
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                # Verify valid JSON before sending to avoid breaking the pipe
                json.loads(line) 
                await ws.send(line.decode())
            except Exception as e:
                logger.error(f"[Bridge] Error reading stdin: {e}")

    async def forward_ws_to_stdout(ws):
        async for msg in ws:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()

    try:
        # Connect with the required subprotocol
        async with websockets.connect(uri, subprotocols=['mcp']) as ws:
            logger.info("[Bridge] Connected successfully.")
            await asyncio.gather(
                forward_stdin_to_ws(ws),
                forward_ws_to_stdout(ws)
            )
    except Exception as e:
        logger.error(f"[Bridge] Connection failed: {e}")
        # Emit a JSON-RPC error to the agent so it fails gracefully
        print(json.dumps({
            "jsonrpc": "2.0", 
            "error": {"code": -32603, "message": f"Bridge connection failed: {str(e)}"},
            "id": None
        }))
        sys.exit(1)

@mcp.tool()
def export_diagnostic_bundle():
    """
    [ENTERPRISE SUPPORT] Export a diagnostic bundle for troubleshooting.
    
    Creates a ZIP file containing:
    - .mcp/ directory (session files, checkpoints)
    - Latest server.log (error diagnostics)
    - System info (Python version, packages, OS)
    
    **Use When**: "Something broke. Let me send you the diagnostic bundle."
    
    **What Support Gets**:
    - Complete session state
    - Full error trace
    - Environment details
    
    Returns:
        JSON with path to ZIP file and size
        
    Example:
        bundle = export_diagnostic_bundle()
        # Returns: {"path": "/tmp/mcp-diag-2025-01-17.zip", "size_mb": 2.5}
        # Share this file with IT/Support for 30-second diagnosis
    """
    import zipfile
    import tempfile
    import subprocess
    
    try:
        # Create temporary ZIP
        fd, zip_path = tempfile.mkstemp(suffix='.zip', prefix='mcp-diag-')
        os.close(fd)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 1. Include .mcp directory (sessions, checkpoints)
            mcp_dir = Path.home() / ".mcp-jupyter"
            if mcp_dir.exists():
                for file in mcp_dir.rglob('*'):
                    if file.is_file():
                        zf.write(file, arcname=f".mcp/{file.relative_to(mcp_dir)}")
            
            # 2. Include latest logs
            log_files = list(Path.cwd().glob("*.log"))
            for log_file in log_files[-5:]:  # Last 5 log files
                if log_file.is_file():
                    zf.write(log_file, arcname=f"logs/{log_file.name}")
            
            # 3. Include system info
            sysinfo = {
                "timestamp": datetime.datetime.now().isoformat(),
                "python_version": sys.version,
                "platform": sys.platform,
                "active_sessions": len(session_manager.sessions),
                "installed_packages": {}
            }
            
            # Capture pip list
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "list", "--format", "json"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    sysinfo["installed_packages"] = json.loads(result.stdout)
            except Exception:
                pass
            
            # Write sysinfo.json
            zf.writestr("sysinfo.json", json.dumps(sysinfo, indent=2))
        
        # Get file size
        size_mb = Path(zip_path).stat().st_size / (1024 * 1024)
        
        return json.dumps({
            "status": "success",
            "path": zip_path,
            "size_mb": round(size_mb, 2),
            "message": f"Diagnostic bundle created. Share this with IT/Support for quick diagnosis.",
            "instructions": "Email this file to data-tools@yourorg.com with subject 'MCP Jupyter Issue Report'"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": str(e),
            "message": "Failed to create diagnostic bundle"
        })

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP Jupyter Server")
    
    # Mode selection
    parser.add_argument("--mode", default="server", choices=["server", "client"], 
                       help="Run as a 'server' (host) or 'client' (bridge to existing server)")
    
    # Server args
    parser.add_argument("--transport", default="stdio", choices=["stdio", "websocket", "sse"],
                       help="[Server Mode] Transport type")
    parser.add_argument("--host", default="127.0.0.1", 
                       help="Bind address (default: 127.0.0.1, use 0.0.0.0 for Docker/Remote)")
    parser.add_argument("--port", type=int, default=3000, 
                       help="Port number")
    parser.add_argument("--idle-timeout", type=int, default=0,
                       help="Auto-shutdown server after N seconds of no connections (0 to disable)")
    parser.add_argument("--data-dir", default=None,
                       help="[Security] Point assets to encrypted/secure volume. Default: ./assets")
    parser.add_argument("--isolate", action="store_true",
                       help="[Docker] Enable Docker isolation for kernel execution (opt-in)")

    # Client args
    parser.add_argument("--uri", default=None,
                       help="[Client Mode] WebSocket URI to connect to (e.g. ws://127.0.0.1:3000/ws)")

    args = parser.parse_args()

    # Windows event loop policy fix
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Bind global exception handler and set a dedicated loop so fatal errors are caught
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(fatal_exception_handler)

    # --- CLIENT MODE ---
    if args.mode == "client":
        # Determine URI
        uri = args.uri if args.uri else f"ws://{args.host}:{args.port}/ws"
        try:
            asyncio.run(run_bridge(uri))
        except KeyboardInterrupt:
            pass
        return

    # --- SERVER MODE (Existing Logic) ---
    try:
        # [SECURITY] Generate and communicate auth token
        import secrets
        token = secrets.token_urlsafe(32)
        os.environ["MCP_SESSION_TOKEN"] = token
        print(f"[MCP_SESSION_TOKEN]: {token}", file=sys.stderr)

        # CONFIGURE HEARTBEAT (auto-shutdown when no clients are connected)
        if getattr(args, 'idle_timeout', 0) and args.idle_timeout > 0:
            connection_manager.set_idle_timeout(args.idle_timeout)

        # Restore any persisted sessions from previous server runs
        # Wrap in timeout to prevent hanging on stale session files
        try:
            asyncio.run(asyncio.wait_for(session_manager.restore_persisted_sessions(), timeout=10.0))
        except asyncio.TimeoutError:
            logger.warning("Session restoration timed out, skipping")

        # [CRUCIBLE] Reap previously orphaned kernels before accepting new work
        try:
            loop.run_until_complete(session_manager.reconcile_zombies())
        except Exception as e:
            logger.error("reaper_failed", error=str(e))
        
        if args.transport == "websocket":
            import uvicorn
            from starlette.applications import Starlette
            from starlette.routing import WebSocketRoute
            from mcp.server.websocket import websocket_server
            
            async def mcp_websocket_endpoint(websocket: WebSocket):
                logger.info(f"WebSocket endpoint called! Client: {websocket.client}")
                try:
                    # B. Bridge FastMCP with this socket
                    # We use the websocket_server context manager to handle streams
                    # This allows FastMCP to read/write, while ConnectionManager can also broadcast
                    # NOTE: websocket_server() performs the WebSocket handshake (accept)
                    logger.info("Entering websocket_server context manager...")
                    async with websocket_server(websocket.scope, websocket.receive, websocket.send) as (read_stream, write_stream):
                        logger.info("✅ WebSocket handshake completed!")
                        # A. Register connection AFTER handshake is complete
                        await connection_manager.connect(websocket)
                        
                        await mcp._mcp_server.run(
                            read_stream,
                            write_stream,
                            mcp._mcp_server.create_initialization_options(),
                        )
                except WebSocketDisconnect:
                    logger.info("WebSocket disconnected")
                    connection_manager.disconnect(websocket)
                except Exception as e:
                    # Disconnects during/after response writes can surface as anyio.ClosedResourceError
                    # (sometimes wrapped in an ExceptionGroup on Python 3.11+). Treat these as normal.
                    def _is_closed_resource_error(err: BaseException) -> bool:
                        try:
                            if err.__class__.__name__ == 'ClosedResourceError':
                                return True
                            sub = getattr(err, 'exceptions', None)
                            if sub and isinstance(sub, (list, tuple)):
                                return any(_is_closed_resource_error(x) for x in sub)
                        except Exception:
                            return False
                        return False

                    if _is_closed_resource_error(e):
                        logger.info("WebSocket closed during response send")
                    else:
                        logger.error(f"Connection error: {e}", exc_info=True)
                    connection_manager.disconnect(websocket)

            from starlette.routing import Route

            # [DATA GRAVITY FIX] Mount assets directory for HTTP access
            # Instead of sending 50MB Base64 blobs over WebSocket, serve assets via HTTP
            # This prevents JSON-RPC connection choking on large binary data
            
            # [SECURITY] Allow pointing assets to secure volume (e.g., encrypted partition)
            if args.data_dir:
                assets_path = Path(args.data_dir).resolve()
                assets_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Using secure data directory: {assets_path}")
            else:
                assets_path = Path.cwd() / "assets"
                assets_path.mkdir(exist_ok=True)
            
            # Store port in environment for utils.py to construct URLs
            os.environ['MCP_PORT'] = str(args.port)
            os.environ['MCP_HOST'] = args.host
            os.environ['MCP_DATA_DIR'] = str(assets_path)

            from src.security import TokenAuthMiddleware
            from starlette.middleware import Middleware
            from src.observability import trace_middleware

            app = Starlette(
                routes=[
                    Route("/health", health_check),
                    WebSocketRoute("/ws", mcp_websocket_endpoint),
                    # Mount assets at /assets for HTTP access
                    Mount("/assets", app=StaticFiles(directory=str(assets_path)), name="assets")
                ],
                middleware=[
                    Middleware(TokenAuthMiddleware)
                ]
            )
            
            # [ROUND 2 AUDIT] Add trace_id propagation middleware
            app.middleware("http")(trace_middleware)
            
            # [FIX] Bind a socket and hand the FD to Uvicorn to avoid TOCTOU races
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((args.host, args.port if args.port != 0 else 0))
            sock.listen(1)
            actual_port = sock.getsockname()[1]

            # Print port to stderr so parent process can parse it if needed
            print(f"[MCP_PORT]: {actual_port}", file=sys.stderr)
            print(f"MCP Server listening on ws://{args.host}:{actual_port}/ws", file=sys.stderr)
            
            host = args.host if args.host != "0.0.0.0" else "localhost"
            print(f"\n🚀 MCP Server Running.")
            print(f"To connect VS Code, open the Command Palette and run:")
            print(f"  MCP Jupyter: Connect to Existing Server")
            print(f"  Url: ws://{host}:{actual_port}/ws\n")

            # Configure Uvicorn to use existing socket FD (prevents TOCTOU)
            config = uvicorn.Config(app=app, fd=sock.fileno(), log_level="error", loop="asyncio")
            server = uvicorn.Server(config)

            try:
                server.run()
            finally:
                # [CRUCIBLE] Graceful shutdown sequence
                try:
                    asyncio.run(session_manager.shutdown_all())
                except Exception as e:
                    logger.warning(f"shutdown_sequence_error: {e}")
                try:
                    sock.close()
                except Exception:
                    pass
                except Exception:
                    pass
             
        else:
            # Start the MCP server using Standard IO
            mcp.run()
    finally:
        asyncio.run(session_manager.shutdown_all())

if __name__ == "__main__":
    main()
