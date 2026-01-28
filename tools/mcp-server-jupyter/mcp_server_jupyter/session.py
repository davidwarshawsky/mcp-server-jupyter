import os
import sys
import asyncio
import uuid
import json
import logging
import nbformat
import datetime

from pathlib import Path
from typing import Dict, Any, Optional
from jupyter_client.manager import AsyncKernelManager
from mcp_server_jupyter import notebook, utils
from mcp_server_jupyter.observability import get_logger, get_tracer
from mcp_server_jupyter.kernel_startup import get_startup_code
from mcp_server_jupyter.kernel_lifecycle import KernelLifecycle
from mcp_server_jupyter.io_multiplexer import IOMultiplexer

# Configure logging
logger = get_logger()
tracer = get_tracer(__name__)

# START: Moved to environment.py but kept for backward compatibility if needed
# Better to import it
from mcp_server_jupyter.environment import get_activated_env_vars as _get_activated_env_vars

# END

import secrets


def _get_kernel_process(km):
    """
    Get the kernel subprocess from a KernelManager.

    In newer versions of jupyter_client, the process is accessed via
    km.provisioner.process instead of the deprecated km.kernel.

    Returns:
        The subprocess.Popen object, or None if not available.
    """
    # Try new way first (jupyter_client >= 7.0)
    if hasattr(km, "provisioner") and km.provisioner:
        process = getattr(km.provisioner, "process", None)
        if process:
            return process
    # Fallback to old way (jupyter_client < 7.0)
    if hasattr(km, "kernel") and km.kernel:
        return km.kernel
    return None


class SessionManager:
    def __init__(
        self, default_execution_timeout: int = 300, input_request_timeout: int = 60
    ):
        # Maps notebook_path (str) -> {
        #   'km': KernelManager,
        #   'kc': Client,
        #   'cwd': str,
        #   'listener_task': asyncio.Task,
        #   'exec_lock': asyncio.Lock  # [RACE CONDITION FIX]
        # }
        self.sessions = {}
        # Global timeout for cell executions (in seconds)
        self.default_execution_timeout = default_execution_timeout

        # Timeout for interactive input requests (seconds)
        self.input_request_timeout = input_request_timeout

        # [PHASE 3.2] Resource Limits
        self.max_concurrent_kernels = int(os.environ.get("MCP_MAX_KERNELS", "10"))
        logger.info(f"Max concurrent kernels: {self.max_concurrent_kernels}")

        # Reference to MCP server for notifications
        self.mcp_server = None
        self.server_session = None
        # [BROADCASTER] Connection manager for multi-user support (set by main.py)
        self.connection_manager = None

        # [PHASE 2 - COMPONENTS] Initialize specialized modules
        self.kernel_lifecycle = KernelLifecycle(
            max_concurrent=self.max_concurrent_kernels
        )
        self.io_multiplexer = IOMultiplexer(input_request_timeout=input_request_timeout)

        # [PHASE 2.3] Asset cleanup task - deferred to avoid "no running event loop" error
        # [IIRB OPS FIX P1] "Infinite Disk" - continuous asset pruning
        self._asset_cleanup_task = None
        self._continuous_cleanup_started = False

        # Removed session restoration logic (in-memory only)

    async def _send_notification(self, method: str, params: Any):
        """Helper to send notifications via available channels (Broadcast)."""

        # 1. Prefer the WebSocket Connection Manager (Multi-User)
        if hasattr(self, "connection_manager") and self.connection_manager:
            msg = {"jsonrpc": "2.0", "method": method, "params": params}
            # This broadcasts to ALL active connections (Human + Agent)
            await self.connection_manager.broadcast(msg)
            return

        # Wrap custom notification to satisfy MCP SDK interface
        class CustomNotification:
            def __init__(self, method, params):
                self.method = method
                self.params = params

            def model_dump(self, **kwargs):
                return {"method": self.method, "params": self.params}

        notification = CustomNotification(method, params)

        # 2. Fallback to individual session notifications
        # This is less efficient but works for single-client setups
        if self.server_session:
            await self.server_session.send_notification(notification)
        elif self.mcp_server and hasattr(self.mcp_server, "send_notification"):
            # Fallback to server level if no sessions registered (e.g. stdio)
            await self.mcp_server.send_notification(notification)

    async def _asset_cleanup_loop(self, interval: int = 3600):
        """
        [ZOMBIE GC FIX - DISABLED]
        
        PREVIOUS IMPLEMENTATION (REMOVED): Autonomously deleted assets based on 
        static analysis of notebook on disk, causing race condition:
        
        1. Cell generates assets/plot.png (in-memory in VS Code)
        2. Background task reads notebook from disk (old version, no reference)
        3. Background task deletes assets/plot.png
        4. User saves notebook (reference is now permanent)
        5. Notebook references deleted file -> CORRUPTION
        
        NEW APPROACH (PersistenceManager.get_expired_assets()):
        - Assets have "leases" (default 24 hours)
        - Client renews lease when notebook is saved
        - Only delete if lease EXPIRED AND asset not in notebook
        - Asset GC must be explicit (triggered by client via tools/asset_tools.py)
        
        This prevents data loss while still cleaning up old files.
        """
        logger.info("[ASSET CLEANUP] Disabled in favor of lease-based GC (see persistence.py)")
        # This method is kept for backward compatibility but does nothing
        # Asset cleanup is now triggered explicitly by the client via asset_tools.py
        pass

    async def _health_check_loop(self, nb_path: str):
        """
        [FIX #4] Background health check to detect and recover from frozen kernels.

        Monitors kernel responsiveness via heartbeat channel. If kernel hangs
        (e.g., infinite C-extension loop), this will detect it and restart.
        """
        check_interval = 30  # Check every 30 seconds
        await asyncio.sleep(check_interval)  # Initial delay

        while True:
            try:
                session = self.sessions.get(nb_path)
                if not session:
                    # Session was stopped
                    break

                kc = session.get("kc")
                if not kc:
                    break

                # Check if kernel is alive via heartbeat
                try:
                    is_alive = kc.is_alive()
                    if hasattr(is_alive, '__await__') or hasattr(is_alive, '__iter__'):
                        is_alive = await is_alive
                except Exception:
                    is_alive = False

                if not is_alive:
                    logger.error(
                        f"[HEALTH CHECK] Kernel {nb_path} died. Attempting restart..."
                    )
                    try:
                        await self.restart_kernel(nb_path)
                    except Exception as e:
                        logger.error(f"[HEALTH CHECK] Failed to restart kernel: {e}")
                        break
                else:
                    # Optional: Send lightweight info request for deeper check
                    try:
                        info_call = kc.kernel_info()
                        # Handle both sync and async kernel_info implementations
                        if hasattr(info_call, "__await__") or hasattr(info_call, "__iter__"):
                            await asyncio.wait_for(info_call, timeout=5.0)
                        else:
                            # Synchronous implementation - call directly (fast path)
                            _ = info_call
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"[HEALTH CHECK] Kernel {nb_path} unresponsive to info request"
                        )
                    except Exception as e:
                        logger.warning(f"[HEALTH CHECK] Error checking kernel: {e}")

                await asyncio.sleep(check_interval)

            except asyncio.CancelledError:
                logger.info(f"[HEALTH CHECK] Task cancelled for {nb_path}")
                break
            except Exception as e:
                logger.error(f"[HEALTH CHECK] Unhandled error: {e}")
                await asyncio.sleep(check_interval)

    def get_python_path(self, venv_path: Optional[str]) -> str:
        """Cross-platform venv resolver"""
        if not venv_path:
            return sys.executable

        root = Path(venv_path).resolve()

        # Windows Check
        if os.name == "nt":
            candidate = root / "Scripts" / "python.exe"
            if candidate.exists():
                return str(candidate)

        # Linux/Mac Check
        candidate = root / "bin" / "python"
        if candidate.exists():
            return str(candidate)

        # Fallback
        return sys.executable

    def get_session_by_pid(self, pid: int) -> Optional[str]:
        """
        [UI TOOL] Find notebook path associated with a specific kernel PID.
        
        Used by the VS Code extension to locate "ghost" sessions that might
        have been created when a notebook was renamed or moved.
        
        Args:
            pid: Process ID of the kernel
            
        Returns:
            Absolute path to the notebook, or None if not found
        """
        for nb_path, session in self.sessions.items():
            kernel_proc = _get_kernel_process(session['km'])
            if kernel_proc and kernel_proc.pid == pid:
                return nb_path
        return None

    async def migrate_session(self, old_path: str, new_path: str) -> bool:
        """
        [RENAME FIX] Move a running kernel from one file path to another.

        Scenario: User finishes work on Friday (draft.ipynb) and renames it
        to final.ipynb on Monday. This method allows the user to keep the
        existing kernel and its variables.

        Updates:
        - In-memory session dictionary (remove old_path, add new_path)

        Args:
            old_path: Original notebook path (with variables)
            new_path: New notebook path (where user is working)

        Returns:
            True if migration succeeded, False if old session not found

        Raises:
            ValueError: If new_path already has an active session
        """
        old_abs = str(Path(old_path).resolve())
        new_abs = str(Path(new_path).resolve())

        if old_abs not in self.sessions:
            logger.warning(f"[MIGRATE] Session not found for {old_abs}")
            return False

        if new_abs in self.sessions:
            raise ValueError(f"[MIGRATE] Target session {new_path} already active")

        logger.info(f"[MIGRATE] Moving kernel from {old_abs} → {new_abs}")

        # Move memory state
        session = self.sessions.pop(old_abs)
        self.sessions[new_abs] = session

        # Update kernel process info
        km = session['km']
        kernel_proc = _get_kernel_process(km)
        env_info = session.get('env_info', {})

        if kernel_proc:
            logger.info(f"[MIGRATE] Session migrated under new path")

        logger.info(f"[MIGRATE] Migration complete: {old_abs} → {new_abs}")
        return True

    def get_all_sessions(self) -> list:
        """
        [UI TOOL] List all running kernels for the Sidebar UI.
        
        Returns a list of session metadata suitable for display in
        the VS Code "Active Kernels" sidebar.
        
        Returns:
            List of dicts with keys: notebook_path, kernel_id, pid, start_time, status
        """
        sessions = []
        
        for nb_path, data in self.sessions.items():
            try:
                env_info = data.get('env_info', {})
                kernel_proc = _get_kernel_process(data['km'])
                pid = kernel_proc.pid if kernel_proc else None
                
                sessions.append({
                    "notebook_path": nb_path,
                    "kernel_id": getattr(data['km'], 'kernel_id', 'unknown'),
                    "pid": pid,
                    "start_time": env_info.get('start_time'),
                    "status": "running"
                })
            except Exception as e:
                logger.error(f"[SESSIONS] Error serializing session {nb_path}: {e}")
                continue
                
        return sessions

    def get_execution_history(self, notebook_path: str, limit: int = 50) -> list:
        """
        [REMOVED] Execution history is now stored in the notebook file on disk.

        Returns empty list since we trust the notebook file as the history record.
        """
        return []

    def get_notebook_history(self, notebook_path: str) -> list:
        """
        [REMOVED] Notebook history is now stored in the notebook file on disk.

        Returns empty list since we trust the notebook file as the history record.
        """
        return []

    async def start_kernel(
        self,
        nb_path: str,
        venv_path: Optional[str] = None,
        timeout: Optional[int] = None,
        agent_id: Optional[str] = None,
    ):
        """
        Start a Jupyter kernel for a notebook.

        [PHASE 2.1 REFACTOR] Now delegates to KernelLifecycle for process management.
        SessionManager retains responsibility for session tracking and I/O multiplexing.

        Args:
            nb_path: Path to the notebook file
            venv_path: Optional path to Python environment (venv/conda)
            timeout: Execution timeout in seconds (default: 300)
            agent_id: Optional agent ID for workspace isolation
        """
        # Ensure asset cleanup task is running (deferred from __init__)
        self._ensure_asset_cleanup_task()

        abs_path = str(Path(nb_path).resolve())
        execution_timeout = (
            timeout if timeout is not None else self.default_execution_timeout
        )

        # Check for Dill (UX Fix)
        if not dill:
            logger.warning(
                "['dill' is missing] State checkpointing/recovery will not work. Install 'dill' in your server environment."
            )

        # Determine notebook directory
        notebook_dir = Path(nb_path).parent.resolve()

        if abs_path in self.sessions:
            return f"Kernel already running for {abs_path}"

        # Start kernel with retries to mitigate transient port-binding failures
        last_error = None
        for attempt in range(3):
            try:
                # [PHASE 2.1] Delegate kernel startup to KernelLifecycle
                km = await self.kernel_lifecycle.start_kernel(
                    kernel_id=abs_path,
                    notebook_dir=notebook_dir,
                    venv_path=venv_path,
                    agent_id=agent_id,
                )

                # Get kernel metadata from lifecycle manager
                kernel_info = self.kernel_lifecycle.get_kernel_info(abs_path)
                py_exe = kernel_info["python_exe"]
                env_name = kernel_info["env_name"]

                # Connect client and wait for ready
                kc = km.client()
                kc.start_channels()
                await kc.wait_for_ready(timeout=120)
                break
            except RuntimeError as e:
                # Kernel limit exceeded
                if "Maximum concurrent kernels" in str(e):
                    oldest_session = min(
                        self.sessions.items(), key=lambda x: x[1].get("start_time", 0)
                    )
                    return json.dumps(
                        {
                            "error": str(e),
                            "suggestion": f"Stop an existing kernel first. Oldest: {oldest_session[0]}",
                            "active_kernels": list(self.sessions.keys()),
                        }
                    )
                last_error = e
            except Exception as e:
                last_error = e

            # Cleanup and retry
            try:
                await self.kernel_lifecycle.stop_kernel(abs_path)
            except Exception:
                pass
            await asyncio.sleep(1.0)
        else:
            raise RuntimeError(
                f"Kernel failed to become ready after retries: {last_error}"
            )

        # Local environment configuration
        py_exe = sys.executable
        env_name = "system"
        kernel_env = os.environ.copy()  # Default: inherit current environment

        # [FINAL PUNCH LIST #1] Inject unique UUID for 100% reliable reaping
        kernel_uuid = str(uuid.uuid4())
        kernel_env["MCP_KERNEL_ID"] = kernel_uuid
        logger.info(f"[KERNEL] Assigning UUID: {kernel_uuid}")

        # Resource limits: on POSIX, prefer to use `prlimit` if available to bound address space
        try:
            import shutil

            prlimit_prefix = (
                ["prlimit", "--as=4294967296"]
                if (os.name != "nt" and shutil.which("prlimit"))
                else []
            )
        except Exception:
            prlimit_prefix = []

            if venv_path:
                venv_path_obj = Path(venv_path).resolve()
                is_conda = (venv_path_obj / "conda-meta").exists()

                py_exe = self.get_python_path(venv_path)
                env_name = venv_path_obj.name

                # Validation
                if not is_conda and not str(py_exe).lower().startswith(
                    str(venv_path_obj).lower()
                ):
                    return f"Error: Could not find python executable in {venv_path}"

                if is_conda:
                    # Prefer resolving env vars and running the env's python directly.
                    try:
                        resolved_env = _get_activated_env_vars(venv_path, py_exe)
                    except Exception:
                        resolved_env = None

                    if resolved_env and "CONDA_PREFIX" in resolved_env:
                        kernel_env = resolved_env
                        cmd = [
                            py_exe,
                            "-m",
                            "ipykernel_launcher",
                            "-f",
                            "{connection_file}",
                        ]
                        km.kernel_cmd = (
                            (prlimit_prefix + cmd) if prlimit_prefix else cmd
                        )
                        logger.info(
                            f"Configured Conda kernel by invoking env python: {km.kernel_cmd}"
                        )
                    else:
                        logger.warning(
                            "Could not resolve conda env activation. Falling back to 'conda run' (interrupts may be unreliable)."
                        )
                        cmd = [
                            "conda",
                            "run",
                            "-p",
                            str(venv_path_obj),
                            "--no-capture-output",
                            "python",
                            "-m",
                            "ipykernel_launcher",
                            "-f",
                            "{connection_file}",
                        ]
                        km.kernel_cmd = (
                            (prlimit_prefix + cmd) if prlimit_prefix else cmd
                        )
                else:
                    # Standard Venv: get activated env or fall back
                    kernel_env = (
                        _get_activated_env_vars(venv_path, py_exe) or os.environ.copy()
                    )
                    bin_dir = str(Path(py_exe).parent)
                    kernel_env["PATH"] = (
                        f"{bin_dir}{os.pathsep}{kernel_env.get('PATH', '')}"
                    )
                    cmd = [
                        py_exe,
                        "-m",
                        "ipykernel_launcher",
                        "-f",
                        "{connection_file}",
                    ]
                    km.kernel_cmd = (prlimit_prefix + cmd) if prlimit_prefix else cmd
            else:
                # No venv: default system Python kernel command
                cmd = [py_exe, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
                km.kernel_cmd = (prlimit_prefix + cmd) if prlimit_prefix else cmd

        # Inject startup code (autoreload, visualization config, etc.)
        kernel_name = getattr(km, "kernel_name", "") or ""
        is_python_kernel = "python" in kernel_name.lower() if kernel_name else True

        if is_python_kernel:
            startup_code = get_startup_code()
            try:
                kc.execute(startup_code, silent=True)
                await asyncio.sleep(0.5)
                logger.info("Autoreload and visualization config sent to kernel")

                # Add cwd to path
                path_code = "import sys, os\nif os.getcwd() not in sys.path: sys.path.append(os.getcwd())"
                kc.execute(path_code, silent=True)
                logger.info("Path setup sent to kernel")
            except Exception as e:
                logger.warning(f"Failed to inject startup code: {e}")
        else:
            logger.info(
                f"Non-Python kernel detected ({kernel_name}). Skipping Python startup injection."
            )

        # Create session structure
        import time

        session_data = {
            "km": km,
            "kc": kc,
            "cwd": kernel_info.get("notebook_dir", str(notebook_dir)),
            "listener_task": None,
            "exec_lock": asyncio.Lock(),
            "execution_timeout": execution_timeout,
            "start_time": time.time(),
            "env_info": {
                "python_path": py_exe,
                "env_name": env_name,
                "start_time": datetime.datetime.now().isoformat(),
            },
        }

        # Start the background listener
        session_data["listener_task"] = asyncio.create_task(
            self._kernel_listener(abs_path, kc)
        )

        # Start the stdin listener (Handles input() requests)
        session_data["stdin_listener_task"] = asyncio.create_task(
            self._stdin_listener(abs_path, session_data)
        )

        # [FIX #4] Start health check loop for this kernel
        session_data["health_check_task"] = asyncio.create_task(
            self._health_check_loop(abs_path)
        )

        self.sessions[abs_path] = session_data

        # Safely get PID and connection file
        pid = "unknown"
        connection_file = "unknown"
        kernel_process = _get_kernel_process(km)
        if kernel_process:
            pid = getattr(kernel_process, "pid", "unknown")
        if hasattr(km, "connection_file"):
            connection_file = km.connection_file

        # Session info tracked in memory only
        if pid != "unknown" and connection_file != "unknown":
            logger.info(f"Kernel session tracked in memory: {abs_path}")

        return f"Kernel started (PID: {pid}). CWD set to: {notebook_dir}"

    async def _kernel_listener(self, nb_path: str, kc):
        """
        Background loop that drains the IOPub channel for a specific kernel.
        [PHASE 2.3] Delegates to IOMultiplexer component.
        """
        session_data = self.sessions.get(nb_path, {})

        # Delegate to IOMultiplexer - direct ZMQ to MCP forwarding
        await self.io_multiplexer.listen_iopub_direct(
            nb_path=nb_path,
            kc=kc,
            notification_callback=self._send_notification,
        )

    async def _broadcast_output(self, message: Dict):
        """Helper to broadcast output to WebSocket clients."""
        if self.connection_manager:
            await self.connection_manager.broadcast(message)

    async def _persist_session_state(self, nb_path: str, session_data: Dict):
        """
        [SMART SYNC FIX] Persist session state (including executed_indices) to disk.

        Called after each cell execution to ensure Smart Sync survives server restarts.
        """
        # Removed persistence - using in-memory only approach
        pass

    async def _stdin_listener(self, nb_path: str, session_data: Dict):
        """
        Background task to handle input() requests from the kernel.
        [PHASE 2.3] Delegates to IOMultiplexer component.
        """
        kc = session_data["kc"]

        # Delegate to IOMultiplexer
        await self.io_multiplexer.listen_stdin(
            nb_path=nb_path,
            kc=kc,
            session_data=session_data,
            notification_callback=self._send_notification,
            interrupt_callback=self.interrupt_kernel,
        )

    async def submit_input(self, notebook_path: str, text: str):
        """Send user input back to the kernel."""
        session = self.get_session(notebook_path)
        if not session:
            raise ValueError("No active session")

        kc = session.get("kc")
        # If we don't have a kernel client (test mode or transient), just clear the flag
        if kc is None:
            session["waiting_for_input"] = False
            logger.info(
                f"No kernel client for {notebook_path}; cleared waiting_for_input flag"
            )
            return

        try:
            kc.input(text)
            logger.info(f"Sent input to {notebook_path}")
        finally:
            # Signal to any pending watchdog that input was provided
            session["waiting_for_input"] = False

    async def execute_cell_async(
        self, nb_path: str, cell_index: int, code: str, exec_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Directly executes code and forwards ZMQ messages as MCP notifications.

        Returns:
            exec_id (str): Unique execution identifier
            None: If kernel is not running
        """
        abs_path = str(Path(nb_path).resolve())
        logger.info(f"execute_cell_async called for {abs_path} cell_index={cell_index}")
        if abs_path not in self.sessions:
            return None

        session = self.sessions[abs_path]
        kc = session.get("kc")
        if not kc:
            return None

        # Generate execution ID if not provided
        if not exec_id:
            exec_id = str(uuid.uuid4())

        # Directly execute the code - ZMQ messages will be forwarded as notifications
        try:
            msg_id = kc.execute(code)
            logger.info(f"Executed code for {exec_id} with msg_id {msg_id}")
        except Exception as e:
            logger.error(f"Failed to execute code for {exec_id}: {e}")
            await self._send_notification(
                "notebook/cell_execution_error",
                {
                    "notebook_path": nb_path,
                    "cell_index": cell_index,
                    "exec_id": exec_id,
                    "error": str(e),
                },
            )
            return None

        # Send MCP notification that execution started
        await self._send_notification(
            "notebook/cell_execution_started",
            {
                "notebook_path": nb_path,
                "cell_index": cell_index,
                "exec_id": exec_id,
                "kernel_msg_id": msg_id,  # Include kernel's message ID
                "code": code,
            },
        )

        return msg_id

    async def get_kernel_info(self, nb_path: str):
        """
        DEPRECATED: Use get_variable_info for specific variables instead.
        Returns overview of all kernel variables (can be large).
        """
        #
        # If we want synchronous-like behavior on top of the async listener:
        # We submit the task, and then we poll `get_execution_status` internally until done.

        code = """
import json
import sys
def _get_var_info():
    info = []
    # Get user variables (exclude imports and dunder methods)
    for name, value in list(globals().items()):
        if name.startswith("_") or hasattr(value, '__module__') and value.__module__ == 'builtins':
            continue
        if isinstance(value, type(sys)): continue # Skip modules
        v_type = type(value).__name__
        v_str = str(value)[:100] 
        details = {}
        if v_type == 'DataFrame' or 'pandas.core.frame.DataFrame' in str(type(value)):
            try:
                v_str = f"DataFrame: {value.shape}"
                details['columns'] = list(value.columns)
                details['dtypes'] = [str(d) for d in value.dtypes.values]
                details['head'] = value.head(3).to_dict(orient='records')
            except Exception: pass
        elif hasattr(value, '__len__') and not isinstance(value, str):
             v_str = f"{v_type}: len={len(value)}"
        info.append({"name": name, "type": v_type, "preview": v_str, "details": details})
    return json.dumps(info)
print(_get_var_info())
"""
        return await self._run_and_wait_internal(nb_path, code)

    # [ROUND 2 AUDIT: REMOVED] Checkpoint features using dill/pickle
    # Recommendation: Use re-execution from history instead of state serialization

    # [ROUND 2 AUDIT: REMOVED] Load checkpoint removed (see save_checkpoint comment above)

    async def get_variable_info(self, nb_path: str, var_name: str):
        """
        Surgical inspection of a specific variable in the kernel.
        Prevents context overflow from dumping all globals.
        """
        code = f"""
import json
import sys

def _inspect_var():
    var_name = '{var_name}'
    if var_name not in globals():
        return json.dumps({{"error": f"Variable '{{var_name}}' not found"}})
    
    value = globals()[var_name]
    v_type = type(value).__name__
    result = {{"name": var_name, "type": v_type}}
    
    # Type-specific inspection
    if 'DataFrame' in str(type(value)):
        try:
            result['shape'] = value.shape
            result['columns'] = list(value.columns)
            result['dtypes'] = {{col: str(dtype) for col, dtype in value.dtypes.items()}}
            result['head'] = value.head(5).to_dict(orient='records')
            result['memory_usage'] = value.memory_usage(deep=True).sum()
        except Exception as e:
            result['error'] = str(e)
    elif hasattr(value, '__len__') and not isinstance(value, str):
        result['length'] = len(value)
        result['preview'] = str(value)[:200]
    elif isinstance(value, (int, float, str, bool)):
        result['value'] = value
    else:
        result['preview'] = str(value)[:200]
    
    return json.dumps(result, indent=2, default=str)

print(_inspect_var())
"""
        return await self._run_and_wait_internal(nb_path, code)

    def get_execution_status(self, nb_path: str, exec_id: str):
        """Get the status of an execution by its ID.

        Since executions are now immediate and messages are forwarded directly,
        we don't track execution status. The notebook file on disk contains the history.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return {"status": "error", "message": "Kernel not found"}

        # Executions are immediate - no status tracking
        return {"status": "completed", "message": "Execution completed (messages forwarded via notifications)"}

    def is_kernel_busy(self, nb_path: str) -> bool:
        """
        Check if the kernel is currently busy executing code.

        Since executions are now immediate, we check if the kernel client reports busy.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return False

        session = self.sessions[abs_path]
        kc = session.get("kc")
        if kc is not None and hasattr(kc, "is_alive"):
            try:
                import inspect
                if inspect.iscoroutinefunction(getattr(kc, "is_alive")):
                    # For async is_alive, assume not busy (can't call sync)
                    return False
                else:
                    return kc.is_alive()
            except Exception:
                pass

        return False

    async def _run_and_wait_internal(self, nb_path: str, code: str):
        """Internal helper to run code via the async system.

        Since executions are immediate, we just execute and return success.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return "Error: No kernel."

        # Execute the code directly
        exec_id = await self.execute_cell_async(nb_path, -1, code)
        if not exec_id:
            return "Error starting internal execution."

        # Since messages are forwarded immediately, we don't need to wait
        return "Code executed (messages forwarded via notifications)"

    async def run_simple_code(self, nb_path: str, code: str):
        return await self._run_and_wait_internal(nb_path, code)

    async def stop_kernel(self, nb_path: str, cleanup_assets: bool = True):
        """
        Stop a running kernel and clean up resources.

        [PHASE 2.1 REFACTOR] Delegates kernel shutdown to KernelLifecycle.
        SessionManager handles session cleanup and asset management.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return "No running kernel."

        session = self.sessions[abs_path]

        # [FIX #8] Session-scoped asset cleanup (GDPR compliance)
        if cleanup_assets:
            try:
                start_time_str = session.get("env_info", {}).get("start_time")
                if start_time_str:
                    import datetime

                    start_time = datetime.datetime.fromisoformat(
                        start_time_str
                    ).timestamp()

                    # Clean up assets created during this session
                    asset_dir = Path(nb_path).parent / "assets"
                    if asset_dir.exists():
                        deleted_count = 0
                        for asset in asset_dir.glob("*"):
                            if asset.is_file() and asset.stat().st_mtime > start_time:
                                try:
                                    asset.unlink()
                                    deleted_count += 1
                                    logger.info(
                                        f"[ASSET CLEANUP] Deleted session asset: {asset.name}"
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"[ASSET CLEANUP] Failed to delete {asset.name}: {e}"
                                    )

                        if deleted_count > 0:
                            logger.info(
                                f"[ASSET CLEANUP] Removed {deleted_count} session-scoped assets"
                            )

                # Also run standard garbage collection
                from mcp_server_jupyter.asset_manager import prune_unused_assets

                cleanup_result = prune_unused_assets(abs_path, dry_run=False)
                logger.info(
                    f"[ASSET CLEANUP] Prune result: {cleanup_result.get('message', 'completed')}"
                )
            except Exception as e:
                logger.warning(f"[ASSET CLEANUP] Failed: {e}")

        # Cancel all background tasks
        tasks_to_cancel = [
            ("listener_task", False),
            ("stdin_listener_task", False),
            ("health_check_task", False),
        ]

        for task_name, needs_signal in tasks_to_cancel:
            if session.get(task_name):
                session[task_name].cancel()
                try:
                    await session[task_name]
                except asyncio.CancelledError:
                    pass

        # Stop client channels
        session["kc"].stop_channels()

        # [PHASE 2.1] Delegate kernel shutdown to lifecycle manager
        await self.kernel_lifecycle.stop_kernel(abs_path)

        # Remove from sessions and clean up state
        del self.sessions[abs_path]

        return "Kernel shutdown."
    async def cancel_execution(self, nb_path: str, exec_id: Optional[str] = None):
        """
        Cancel current execution by interrupting the kernel.

        Since executions are immediate, this interrupts any currently running code.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return "No kernel."

        session = self.sessions[abs_path]

        # Send interrupt signal to kernel
        try:
            await session["km"].interrupt_kernel()
            logger.info(f"Sent interrupt signal to kernel for {nb_path}")
            return "Execution interrupted"
        except Exception as e:
            logger.error(f"Failed to interrupt kernel: {e}")
            return f"Failed to interrupt: {e}"

    async def shutdown_all(self):
        """Kills all running kernels and cleans up persisted session files."""
        for abs_path, session in list(self.sessions.items()):
            if session.get("listener_task"):
                session["listener_task"].cancel()
            try:
                await session["km"].shutdown_kernel(now=True)
                # Session cleanup handled by clearing sessions dict
            except Exception as e:
                logging.error(f"Error shutting down kernel for {abs_path}: {e}")
        self.sessions.clear()

    # --- Preserved Helper Methods ---

    async def install_package(self, nb_path: str, package_name: str):
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return "Error: No running kernel to install into."

        session = self.sessions[abs_path]
        km = session["km"]
        cmd = km.kernel_cmd
        if not cmd:
            return "Error: Could not determine kernel python path."

        python_executable = cmd[0]

        # Run pip install
        proc = await asyncio.create_subprocess_exec(
            python_executable,
            "-m",
            "pip",
            "install",
            package_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        output = f"Stdout: {stdout.decode()}\nStderr: {stderr.decode()}"
        if proc.returncode == 0:
            # FIXED: Invalidate import caches so kernel sees new package immediately
            invalidation_code = "import importlib; importlib.invalidate_caches(); print('Caches invalidated.')"
            # Use -1 index for internal/maintenance commands if session supports queued executions
            # Best-effort: try to inject the invalidation code; if the session isn't fully
            # initialized (e.g., during unit tests), catch and log the error but still report success.
            try:
                await self.execute_cell_async(nb_path, -1, invalidation_code)
            except Exception as e:
                logger.info(f"Cache invalidation (best-effort) failed or skipped: {e}")

            return f"Successfully installed {package_name}.\n{output}"
        else:
            return f"Failed to install {package_name}.\n{output}"

    async def list_packages(self, nb_path: str):
        # This uses run_simple_code currently in main, but we can implement it here too
        pass  # Using main.py's implementation which calls run_simple_code

    async def interrupt_kernel(self, nb_path: str):
        """
        Send SIGINT to kernel (KeyboardInterrupt).

        [PHASE 2.1 REFACTOR] Delegates to KernelLifecycle for process signal.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return "No running kernel."

        # [PHASE 2.1] Delegate interrupt to lifecycle manager
        success = await self.kernel_lifecycle.interrupt_kernel(abs_path)

        if success:
            logger.info(f"[KERNEL] Interrupted {abs_path}")
            return "Kernel interrupted (SIGINT sent)."
        else:
            return "Error: Failed to interrupt kernel."

    async def restart_kernel(self, nb_path: str):
        """
        Restart a kernel (clears memory but preserves outputs).

        [PHASE 2.1 REFACTOR] Delegates kernel restart to KernelLifecycle.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return "Error: No running kernel."

        # [ASSET CLEANUP] Run GC before restart
        try:
            from mcp_server_jupyter.asset_manager import prune_unused_assets

            cleanup_result = prune_unused_assets(abs_path, dry_run=False)
            logger.info(
                f"Asset cleanup on kernel restart: {cleanup_result.get('message', 'completed')}"
            )
        except Exception as e:
            logger.warning(f"Asset cleanup on restart failed: {e}")

        # Clear session state
        session = self.sessions[abs_path]
        session["executions"].clear()
        session["queued_executions"].clear()
        session["executed_indices"].clear()
        session["execution_counter"] = 0
        session["max_executed_index"] = -1

        # [PHASE 2.1] Delegate kernel restart to lifecycle manager
        success = await self.kernel_lifecycle.restart_kernel(abs_path)

        if success:
            logger.info(f"[KERNEL] Restarted {abs_path}")
            return "Kernel restarted."
        else:
            return "Error: Failed to restart kernel."

    def list_environments(self):
        """Scans for potential Python environments."""
        envs = []

        # 1. Current System Python
        envs.append({"name": "System/Global", "path": sys.executable})

        # 2. Check common locations relative to user home
        try:
            from mcp_server_jupyter.config import load_and_validate_settings

            _cfg = load_and_validate_settings()
            home = _cfg.get_data_dir().parent if _cfg.MCP_DATA_DIR else Path.home()
        except Exception:
            home = Path.home()

        candidates = [
            home / ".virtualenvs",
            home / "miniconda3" / "envs",
            home / "anaconda3" / "envs",
            Path("."),  # Current folder
            Path(".venv"),
            Path("venv"),
            Path("env"),
        ]

        for folder in candidates:
            if folder.exists():
                if (folder / "bin" / "python").exists():
                    envs.append({"name": f"Venv ({folder.name})", "path": str(folder)})
                elif (folder / "Scripts" / "python.exe").exists():
                    envs.append({"name": f"Venv ({folder.name})", "path": str(folder)})
                elif folder.is_dir():
                    # Scan subfolders (common for .virtualenvs or conda)
                    for sub in folder.iterdir():
                        if sub.is_dir():
                            if (sub / "bin" / "python").exists():
                                envs.append(
                                    {"name": f"Found: {sub.name}", "path": str(sub)}
                                )

        return envs

    def get_kernel_resources(self, nb_path: str) -> Dict[str, Any]:
        """
        [PHASE 3.4] Get CPU and RAM usage of the kernel process.
        Returns resource metrics for monitoring and auto-restart logic.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return {"error": "No active kernel"}

        # Lazy import psutil to prevent startup crashes on systems with broken binary wheels
        try:
            import psutil
        except ImportError:
            return {"error": "psutil not installed. Install with: pip install psutil"}

        try:
            km = self.sessions[abs_path]["km"]

            # Safely get PID using the helper
            kernel_process = _get_kernel_process(km)
            if not kernel_process:
                return {"error": "Kernel process not found"}

            pid = getattr(kernel_process, "pid", None)
            if not pid:
                return {"error": "Kernel PID not available"}

            proc = psutil.Process(pid)

            # Get children processes (kernels sometimes spawn subprocesses)
            children = proc.children(recursive=True)
            total_mem = proc.memory_info().rss
            total_cpu = proc.cpu_percent(interval=0.1)

            for child in children:
                try:
                    total_mem += child.memory_info().rss
                    total_cpu += child.cpu_percent(interval=0.1)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            return {
                "status": "active",
                "pid": pid,
                "memory_mb": round(total_mem / 1024 / 1024, 2),
                "memory_percent": round(proc.memory_percent(), 1),
                "cpu_percent": round(total_cpu, 1),
                "num_threads": proc.num_threads(),
                "num_children": len(children),
            }
        except Exception as e:
            # Catch all exceptions including psutil.NoSuchProcess
            # Check if it's a zombie kernel specifically
            if "NoSuchProcess" in str(type(e).__name__):
                return {"error": "Kernel process no longer exists (zombie state)"}
            return {"error": str(e)}

    def get_session(self, nb_path: str):
        abs_path = str(Path(nb_path).resolve())
        return self.sessions.get(abs_path)

    async def reconcile_zombies(self):
        """
        [CRUCIBLE] Startup Task: Kill orphan kernels from dead server processes.
        """
        # Removed - let OS handle process cleanup (local-first approach)
        pass


# --- Compatibility wrapper for finalizing executions synchronously ---
# Attach at module-level to avoid interfering with async control flow inside the class
def _finalize_execution(self, nb_path: str, exec_data: Dict):
    """Synchronous wrapper for finalizing an execution. Executes in-thread to completion.

    If an event loop is present on this thread, the async finalizer is executed in a
    background thread using asyncio.run to prevent interfering with the running loop.
    Otherwise, it is executed inline with asyncio.run.
    """
    try:
        asyncio.get_running_loop()
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(
                asyncio.run, self._finalize_execution_async(nb_path, exec_data)
            )
            return fut.result()
    except RuntimeError:
        # No running loop — run synchronously
        return asyncio.run(self._finalize_execution_async(nb_path, exec_data))


# Attach wrapper to class
SessionManager._finalize_execution = _finalize_execution
