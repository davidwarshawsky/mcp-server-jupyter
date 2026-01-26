import os
import sys
import asyncio
import uuid
import json
import logging
import nbformat
import datetime

try:
    import dill
except ImportError:
    dill = None
from pathlib import Path
from typing import Dict, Any, Optional
from jupyter_client.manager import AsyncKernelManager
from src import notebook, utils
from src.observability import get_logger, get_tracer
from src.kernel_state import KernelStateManager
from src.kernel_startup import INSPECT_HELPER_CODE, get_startup_code
from src.kernel_lifecycle import KernelLifecycle
from src.execution_scheduler import ExecutionScheduler
from src.io_multiplexer import IOMultiplexer

# Configure logging
logger = get_logger()
tracer = get_tracer(__name__)

# START: Moved to environment.py but kept for backward compatibility if needed
# Better to import it
from src.environment import get_activated_env_vars as _get_activated_env_vars

# END

import secrets


def get_or_create_secret():
    """
    [SECURITY FIX] Get or create persistent session secret.

    The secret is stored in $MCP_DATA_DIR/secret.key with 0o600 permissions.
    This ensures checkpoints remain valid across server restarts.
    """
    from src.config import load_and_validate_settings

    settings = load_and_validate_settings()
    secret_path = settings.get_data_dir() / "secret.key"

    if secret_path.exists():
        return secret_path.read_bytes()

    # Generate new secret
    secret = secrets.token_bytes(32)

    # Create directory with restricted permissions
    secret_path.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    with open(secret_path, "wb") as f:
        f.write(secret)

    # Set permissions to user-only read/write (chmod 600)
    os.chmod(secret_path, 0o600)

    return secret


# Generate a persistent session secret used to sign local checkpoints.
# This ensures checkpoints remain valid across server restarts.
SESSION_SECRET = get_or_create_secret()


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
        #   'executions': Dict[str (msg_id), Dict],
        #   'queued_executions': Dict[str (exec_id), Dict],  # Track queued before processing
        #   'execution_queue': asyncio.Queue,
        #   'queue_processor_task': asyncio.Task,
        #   'execution_counter': int,
        #   'stop_on_error': bool,
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

        # Session persistence directory (12-Factor compliant)
        from src.config import load_and_validate_settings

        _settings = load_and_validate_settings()
        self.persistence_dir = _settings.get_data_dir() / "sessions"
        self.persistence_dir.mkdir(parents=True, exist_ok=True)

        # [PHASE 2 - COMPONENTS] Initialize specialized modules
        self.state_manager = KernelStateManager(self.persistence_dir)
        self.kernel_lifecycle = KernelLifecycle(
            max_concurrent=self.max_concurrent_kernels
        )
        self.execution_scheduler = ExecutionScheduler(
            default_timeout=default_execution_timeout
        )
        self.io_multiplexer = IOMultiplexer(input_request_timeout=input_request_timeout)

        # [PHASE 2.3] Asset cleanup task - deferred to avoid "no running event loop" error
        # [IIRB OPS FIX P1] "Infinite Disk" - continuous asset pruning
        self._asset_cleanup_task = None
        self._continuous_cleanup_started = False

        # Restore persisted sessions on startup if event loop is available.
        # If SessionManager is constructed before the event loop exists (e.g., in import-time during tests),
        # we defer restoration until later.
        self._restore_pending = False
        try:
            # Try to schedule restoration (will raise RuntimeError if no running loop)
            import asyncio

            asyncio.get_running_loop()
            try:
                asyncio.create_task(self.restore_persisted_sessions())
                logger.info("Scheduled restore of persisted sessions on startup")
            except Exception as e:
                logger.warning(f"Could not schedule restore_persisted_sessions immediately: {e}")
        except RuntimeError:
            # No running loop - set flag to start restoration later
            self._restore_pending = True
            logger.info("Event loop not present; will restore persisted sessions when loop starts")

    def _ensure_asset_cleanup_task(self):
        """Start the asset cleanup task if not already running."""
        if self._asset_cleanup_task is None or self._asset_cleanup_task.done():
            try:
                # [IIRB OPS FIX P1] Start continuous asset pruner (1h interval)
                # This ensures disk doesn't fill up on long-running servers
                self._asset_cleanup_task = asyncio.create_task(
                    self._asset_cleanup_loop(interval=3600)
                )
                self._continuous_cleanup_started = True
                logger.info("[OPS] Continuous asset pruner started (interval: 1h)")
            except RuntimeError:
                # No running event loop - task will be started later
                pass

    def set_mcp_server(self, mcp_server):
        """Set the MCP server instance to enable notifications."""
        self.mcp_server = mcp_server
        # [BROADCASTER] Optional connection manager for multi-user support
        self.connection_manager = None

        # If restore was pending due to missing event loop at construction time,
        # schedule it now that the server is wiring things up and the loop should be running.
        if getattr(self, "_restore_pending", False):
            try:
                import asyncio

                asyncio.create_task(self.restore_persisted_sessions())
                self._restore_pending = False
                logger.info("Deferred restore_persisted_sessions scheduled via set_mcp_server")
            except Exception as e:
                logger.warning(f"Failed to schedule deferred restore: {e}")

    def register_session(self, session):
        """Register a client session for sending notifications."""
        if not hasattr(self, "active_sessions"):
            self.active_sessions = set()

        self.active_sessions.add(session)
        logger.info(
            f"Registered new client session. Total active: {len(self.active_sessions)}"
        )

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
        [PHASE 2.3] Periodically cleans up old asset files to prevent disk space exhaustion.
        Runs every hour by default and deletes files older than 24 hours.

        [ROUND 2 AUDIT] Also cleanup old proposals.json entries.
        """
        logger.info(f"Starting Asset Cleanup task (scan interval: {interval}s)")
        max_age_hours = int(os.environ.get("MCP_ASSET_MAX_AGE_HOURS", "24"))
        await asyncio.sleep(interval)  # Initial delay

        while True:
            try:
                assets_dir = Path("assets")
                if not assets_dir.exists():
                    await asyncio.sleep(interval)
                    continue

                import time

                now = time.time()
                max_age_seconds = max_age_hours * 3600
                deleted_count = 0

                for asset_file in assets_dir.glob("*"):
                    if asset_file.is_file():
                        try:
                            file_age = now - asset_file.stat().st_mtime
                            if file_age > max_age_seconds:
                                asset_file.unlink()
                                deleted_count += 1
                                logger.debug(
                                    f"[ASSET CLEANUP] Deleted old asset: {asset_file.name} (age: {file_age/3600:.1f}h)"
                                )
                        except Exception as e:
                            logger.warning(
                                f"[ASSET CLEANUP] Failed to delete {asset_file.name}: {e}"
                            )

                if deleted_count > 0:
                    logger.info(
                        f"[ASSET CLEANUP] Deleted {deleted_count} old assets (>{max_age_hours}h)"
                    )

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("Asset cleanup task cancelled.")
                break
            except Exception as e:
                logger.error(f"[ASSET CLEANUP] Unhandled error: {e}")
                await asyncio.sleep(interval)

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

    async def restore_persisted_sessions(self):
        """
        Attempt to restore sessions from disk on server startup.

        Checks if kernel PIDs are still alive and reconnects if possible.
        Cleans up stale session files for dead kernels.
        """
        restored_count = 0
        cleaned_count = 0

        for session_file in self.state_manager.get_persisted_sessions():
            try:
                with open(session_file, "r") as f:
                    session_data = json.load(f)

                nb_path = session_data["notebook_path"]
                pid = session_data["pid"]
                connection_file = session_data["connection_file"]
                saved_create_time = session_data.get("pid_create_time")

                # Check if kernel process is still alive
                try:
                    # Lazy import to avoid startup crashes
                    import psutil

                    # [REAPER FIX] Validate create_time to ensure PID wasn't recycled
                    pid_valid = False
                    if psutil.pid_exists(pid):
                        try:
                            proc = psutil.Process(pid)
                            # If we have saved create_time, verify it matches
                            if (
                                saved_create_time is None
                                or proc.create_time() == saved_create_time
                            ):
                                pid_valid = True
                            else:
                                logger.warning(
                                    f"PID {pid} was reused. Skipping restoration."
                                )
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                    if pid_valid and Path(connection_file).exists():
                        # Try to reconnect to existing kernel
                        logger.info(
                            f"Attempting to restore session for {nb_path} (PID: {pid})"
                        )

                        try:
                            # Create kernel manager from existing connection file
                            km = AsyncKernelManager(connection_file=connection_file)
                            km.load_connection_file()

                            # Create client and connect
                            kc = km.client()
                            kc.start_channels()

                            # Test if kernel is responsive
                            await asyncio.wait_for(
                                kc.wait_for_ready(timeout=10), timeout=15
                            )

                            # Get notebook directory for CWD
                            notebook_dir = str(Path(nb_path).parent.resolve())

                            # Restore session structure
                            abs_path = str(Path(nb_path).resolve())
                            # [SECURITY] Bounded queue prevents DoS from runaway executions
                            max_queue_size = int(
                                os.environ.get("MCP_MAX_QUEUE_SIZE", "1000")
                            )

                            # [SMART SYNC FIX] Restore executed_indices from persisted state
                            restored_indices = set(
                                session_data.get("executed_indices", [])
                            )

                            session_dict = {
                                "km": km,
                                "kc": kc,
                                "cwd": notebook_dir,
                                "listener_task": None,
                                "executions": {},
                                "queued_executions": {},
                                "execution_queue": asyncio.Queue(
                                    maxsize=max_queue_size
                                ),
                                "execution_counter": 0,
                                "stop_on_error": False,
                                "exec_lock": asyncio.Lock(),  # [RACE CONDITION FIX]
                                "executed_indices": restored_indices,  # [SMART SYNC FIX]
                                "env_info": session_data.get(
                                    "env_info",
                                    {
                                        "python_path": "unknown",
                                        "env_name": "unknown",
                                        "start_time": session_data.get(
                                            "created_at", "unknown"
                                        ),
                                    },
                                ),
                            }

                            # Start background tasks
                            session_dict["listener_task"] = asyncio.create_task(
                                self._kernel_listener(
                                    abs_path, kc, session_dict["executions"]
                                )
                            )
                            session_dict["queue_processor_task"] = asyncio.create_task(
                                self._queue_processor(abs_path, session_dict)
                            )

                            self.sessions[abs_path] = session_dict
                            restored_count += 1
                            logger.info(f"Successfully restored session for {nb_path}")

                        except Exception as reconnect_error:
                            logger.warning(
                                f"Failed to reconnect to kernel PID {pid}: {reconnect_error}"
                            )
                            # Clean up the stale session file
                            session_file.unlink()
                            cleaned_count += 1
                    else:
                        # Kernel is dead or connection file missing, clean up
                        if not psutil.pid_exists(pid):
                            logger.info(
                                f"Kernel PID {pid} for {nb_path} is dead, cleaning up"
                            )
                        else:
                            # [GRIM REAPER] If PID exists but we can't connect/verify, kill it to prevent zombies
                            logger.warning(
                                f"Kernel PID {pid} exists but connection file is missing/invalid. Killing zombie process."
                            )
                            try:
                                proc = psutil.Process(pid)
                                proc.terminate()
                                # Give it a moment to die gracefully
                                try:
                                    proc.wait(timeout=2.0)
                                except psutil.TimeoutExpired:
                                    proc.kill()
                            except Exception as cleanup_error:
                                logger.warning(
                                    f"Failed to kill zombie kernel {pid}: {cleanup_error}"
                                )
                        session_file.unlink()
                        cleaned_count += 1
                except ImportError:
                    logger.warning("psutil not available, skipping session restoration")
                    break

            except Exception as e:
                logger.warning(f"Failed to restore session from {session_file}: {e}")
                # Clean up corrupted session file
                try:
                    session_file.unlink()
                except:
                    pass

        if restored_count > 0:
            logger.info(f"Restored {restored_count} sessions from disk")
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} stale session files")

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

    def _validate_mount_path(self, project_root: Path) -> Path:
        """
        [SECURITY] Validate Docker mount path to prevent container breakout attacks.

        Ensures the mount path is within allowed directories and doesn't
        escape via symlinks or .. traversal.

        IIRB COMPLIANCE: Blocks mounting of root (/) or system paths.
        """
        resolved_root = project_root.resolve()

        # [CRITICAL] Block mounting root separately (every path is_relative_to /)
        if resolved_root == Path("/"):
            raise ValueError(
                "SECURITY VIOLATION: Cannot mount root directory /. "
                "Mounting the root filesystem is forbidden."
            )

        # Block system paths (but /tmp is allowed for testing)
        dangerous_paths = [
            Path("/etc"),
            Path("/var"),
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/boot"),
            Path("/sys"),
        ]
        for dangerous in dangerous_paths:
            if resolved_root == dangerous or resolved_root.is_relative_to(dangerous):
                raise ValueError(
                    f"SECURITY VIOLATION: Cannot mount system path {resolved_root}. "
                    f"Mounting root or system directories is forbidden."
                )

        # Define allowed base paths (configurable via environment)
        # [P0 FIX #2] Use config-based data directory as fallback
        try:
            from src.config import load_and_validate_settings

            _cfg = load_and_validate_settings()
            default_allowed = (
                _cfg.get_data_dir().parent if _cfg.MCP_DATA_DIR else Path.home()
            )
        except Exception:
            default_allowed = Path.home()

        # Allow both configured path and /tmp (for testing)
        allowed_bases = [
            Path(os.environ.get("MCP_ALLOWED_ROOT", str(default_allowed))).resolve(),
            Path("/tmp").resolve(),
        ]

        # Containment check - path must be under at least one allowed base
        is_allowed = False
        for allowed_base in allowed_bases:
            try:
                resolved_root.relative_to(allowed_base)
                is_allowed = True
                break
            except ValueError:
                continue

        if not is_allowed:
            raise ValueError(
                f"Security Violation: Cannot mount path {resolved_root} "
                f"outside of allowed bases. "
                f"Set MCP_ALLOWED_ROOT environment variable to change this."
            )

        logger.info(f"[SECURITY] Validated mount path: {resolved_root}")
        return resolved_root

    async def start_kernel(
        self,
        nb_path: str,
        venv_path: Optional[str] = None,
        docker_image: Optional[str] = None,
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
            docker_image: Optional docker image to run kernel safely inside
            timeout: Execution timeout in seconds (default: 300)
            agent_id: Optional agent ID for workspace isolation
        """
        # Ensure asset cleanup task is running (deferred from __init__)
        self._ensure_asset_cleanup_task()

        abs_path = str(Path(nb_path).resolve())
        execution_timeout = (
            timeout if timeout is not None else self.default_execution_timeout
        )
        container_name = None

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
        # Ensure scoped_workdir is defined for non-docker kernels to avoid UnboundLocalError
        scoped_workdir = None
        for attempt in range(3):
            try:
                # [PHASE 2.1] Delegate kernel startup to KernelLifecycle
                km = await self.kernel_lifecycle.start_kernel(
                    kernel_id=abs_path,
                    notebook_dir=notebook_dir,
                    venv_path=venv_path,
                    docker_image=docker_image,
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

        if docker_image:
            # [PHASE 4: Docker Support]
            # Strategy: Use docker run to launch the kernel
            # We must mount:
            # 1. The workspace (so imports work)
            # 2. The connection file (so we can talk to it)

            # [FINAL PUNCH LIST #1] Inject unique UUID for 100% reliable reaping
            kernel_uuid = str(uuid.uuid4())
            container_name = f"mcp-kernel-{kernel_uuid}"
            logger.info(f"[KERNEL] Assigning UUID (Docker): {kernel_uuid}")

            # Locate workspace root for proper relative imports
            project_root = utils.get_project_root(Path(notebook_dir))

            # [FIX #5] Validate mount path to prevent path traversal
            project_root = self._validate_mount_path(project_root)

            # Pre-flight scan for obviously sensitive files (e.g., .env, .ssh)
            try:
                from src.docker_security import validate_mount_source

                validate_mount_source(project_root)
            except Exception as e:
                raise RuntimeError(
                    f"Mount source validation failed for {project_root}: {e}"
                )

            str(project_root)

            # [DAY 3 - SCOPED MOUNTS] Create a temporary scoped workspace that only
            # contains the notebook file and an optional 'data/' folder. This reduces
            # blast radius when mounting into containers.
            import tempfile
            import shutil

            scoped_workdir = None
            try:
                # [FIX: DOCKER MOUNT ERRORS]
                # Create a temporary scoped workspace INSIDE project root (not /tmp)
                # This avoids Docker Desktop permission errors on mounted volumes
                import tempfile
                import shutil

                # [DAY 3 OPT 3.1] Define sensitive file filter
                def sensitive_file_filter(src, names):
                    """Filter function to exclude sensitive files during copytree."""
                    ignored = []
                    for name in names:
                        # Block hidden files (except .gitignore), env files, key files, node_modules, __pycache__
                        if (name.startswith('.') and name != '.gitignore') or \
                           name.endswith('.env') or \
                           'credentials' in name.lower() or \
                           'secret' in name.lower() or \
                           'api_key' in name.lower() or \
                           'token' in name.lower() or \
                           'password' in name.lower() or \
                           name in ('node_modules', '__pycache__', '.git', '.venv', 'venv'):
                            ignored.append(name)
                    return ignored

                # 1. Create .mcp_workspaces inside the project root
                # This directory is likely already allowed in Docker File Sharing settings
                workspaces_root = Path(project_root) / ".mcp_workspaces"
                try:
                    workspaces_root.mkdir(exist_ok=True)
                except (PermissionError, OSError):
                    # [FINAL FIX: READ-ONLY FALLBACK] Project root is read-only
                    # Fall back to system temp directory
                    logger.warning(f"[FS PERMISSION] Project root {project_root} is read-only. Using system temp.")
                    workspaces_root = Path(tempfile.gettempdir()) / "mcp_workspaces_fallback"
                    workspaces_root.mkdir(exist_ok=True)
                
                # 2. Add gitignore to prevent pollution
                gitignore = workspaces_root / ".gitignore"
                if not gitignore.exists():
                    gitignore.write_text("*\n")

                # 3. Create temp dir INSIDE .mcp_workspaces
                tmpdir = Path(tempfile.mkdtemp(prefix=f"session_{kernel_uuid}_", dir=str(workspaces_root)))
                
                # Copy only the notebook file
                nb_src = Path(nb_path)
                nb_dest = tmpdir / nb_src.name
                shutil.copy2(nb_src, nb_dest)

                # Copy data/ folder if exists, applying sensitive file filter
                data_src = Path(project_root) / "data"
                if data_src.exists() and data_src.is_dir():
                    shutil.copytree(
                        data_src, 
                        tmpdir / "data",
                        ignore=sensitive_file_filter,  # Apply security filter
                        dirs_exist_ok=True
                    )

                # Ensure assets directory exists
                (tmpdir / "assets").mkdir(exist_ok=True)

                scoped_workdir = tmpdir
                # Override root for Docker mount
                project_root = scoped_workdir
                logger.info(f"[SCOPED MOUNTS] Created local workspace: {scoped_workdir}")
            except Exception as e:
                logger.warning(f"Failed to create local scoped workspace: {e}. Falling back to full mount.")

            # [SECURITY] Implement "Sandbox Subdirectory" pattern
            # Mount source code read-only, but provide a read-write sandbox for outputs.
            sandbox_dir = project_root / ".mcp_sandbox"
            sandbox_dir.mkdir(exist_ok=True)

            # Calculate CWD inside container, which is now the sandbox
            container_cwd = "/workspace/sandbox"

            # Construct Docker Command
            uid_args = ["-u", str(os.getuid())] if os.name != "nt" else ["-u", "1000"]
            cmd = (
                [
                    "docker",
                    "run",
                    "--rm",  # Cleanup container on exit
                    f"--name={container_name}",  # Explicit name for reaper
                    "-i",  # Interactive (keeps stdin open)
                    "--init",  # Ensure PID 1 forwards signals to children
                    "--network",
                    "none",  # [SECURITY] Disable networking
                    "--security-opt",
                    "no-new-privileges",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=1g",
                    # Mount source code read-only for reference
                    "-v",
                    f"{project_root}:/workspace/source:ro",
                    # Mount sandbox read-write for assets/outputs
                    "-v",
                    f"{sandbox_dir}:/workspace/sandbox:rw",
                    "-v",
                    "{connection_file}:/kernel.json:ro",
                    "-w",
                    container_cwd,  # CWD is the sandbox
                ]
                + uid_args
                + [
                    docker_image,
                    "python",
                    "-m",
                    "ipykernel_launcher",
                    "-f",
                    "/kernel.json",
                ]
            )

            # Resource limit for Docker: cap memory to 4GB to avoid noisy neighbor OOMs
            cmd.insert(2, "--memory")
            cmd.insert(3, "4g")

            km.kernel_cmd = cmd
            logger.info(f"Configured Docker kernel: {cmd}")

            # We explicitly do NOT activate local envs if using Docker
            # Docker image is the environment
            kernel_env = {}

            # Set metadata for session tracking
            py_exe = "python"  # Inside container
            env_name = f"docker:{docker_image}"

        else:
            # 1. Handle Environment (Local)
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

        max_queue_size = int(os.environ.get("MCP_MAX_QUEUE_SIZE", "1000"))
        session_data = {
            "km": km,
            "kc": kc,
            "cwd": kernel_info.get("notebook_dir", str(notebook_dir)),
            "listener_task": None,
            "executions": {},
            "queued_executions": {},
            "execution_queue": asyncio.Queue(maxsize=max_queue_size),
            "executed_indices": set(),
            "execution_counter": 0,
            "max_executed_index": -1,
            "stop_on_error": False,
            "execution_timeout": execution_timeout,
            "start_time": time.time(),
            "scoped_workdir": str(scoped_workdir) if scoped_workdir else None,
            "env_info": {
                "python_path": py_exe,
                "env_name": env_name,
                "start_time": datetime.datetime.now().isoformat(),
                "container_name": container_name,
            },
        }

        # Start the background listener
        session_data["listener_task"] = asyncio.create_task(
            self._kernel_listener(abs_path, kc, session_data["executions"])
        )

        # Start the stdin listener (Handles input() requests)
        session_data["stdin_listener_task"] = asyncio.create_task(
            self._stdin_listener(abs_path, session_data)
        )

        # Start the execution queue processor
        session_data["queue_processor_task"] = asyncio.create_task(
            self._queue_processor(abs_path, session_data)
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

        # Persist session info to prevent zombie kernels after server restart
        if pid != "unknown" and connection_file != "unknown":
            self.state_manager.persist_session(
                abs_path,
                connection_file,
                pid,
                session_data["env_info"],
                kernel_uuid,
                session_data.get("executed_indices", set()),
            )

        return f"Kernel started (PID: {pid}). CWD set to: {notebook_dir}"

    async def _kernel_listener(self, nb_path: str, kc, executions: Dict):
        """
        Background loop that drains the IOPub channel for a specific kernel.
        [PHASE 2.3] Delegates to IOMultiplexer component.
        """
        session_data = self.sessions.get(nb_path, {})

        # Delegate to IOMultiplexer
        await self.io_multiplexer.listen_iopub(
            nb_path=nb_path,
            kc=kc,
            executions=executions,
            session_data=session_data,
            finalize_callback=self._finalize_execution_async,
            broadcast_callback=self._broadcast_output,
            notification_callback=self._send_notification,
            persist_callback=self._persist_session_state,
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
        try:
            session = self.sessions.get(nb_path)
            if not session:
                return

            # Get kernel info for persistence
            km = session.get("km")
            pid = "unknown"
            connection_file = "unknown"

            kernel_process = _get_kernel_process(km)
            if kernel_process:
                pid = getattr(kernel_process, "pid", "unknown")
            if hasattr(km, "connection_file"):
                connection_file = km.connection_file

            if pid != "unknown" and connection_file != "unknown":
                # Re-persist with updated executed_indices
                self.state_manager.persist_session(
                    nb_path,
                    connection_file,
                    pid,
                    session.get("env_info", {}),
                    getattr(km, "kernel_id", None),
                    session.get("executed_indices", set()),
                )
        except Exception as e:
            logger.warning(f"Failed to persist session state for {nb_path}: {e}")

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

    async def _queue_processor(self, nb_path: str, session_data: Dict):
        """
        Background loop that processes execution requests from the queue.
        Ensures only one cell executes at a time per notebook.

        REFACTORED: Delegates to ExecutionScheduler component.
        """

        # Create execute callback that uses the kernel client
        async def execute_callback(code: str) -> str:
            """Execute code and return message ID."""
            kc = session_data["kc"]
            return kc.execute(code)

        # Delegate to ExecutionScheduler
        await self.execution_scheduler.process_queue(
            nb_path=nb_path,
            session_data=session_data,
            execute_callback=execute_callback,
        )

    async def _finalize_execution_async(self, nb_path: str, exec_data: Dict):
        """Async implementation of finalizing an execution. Use `_finalize_execution` wrapper for sync callers."""
        try:
            # 1. Save Assets and get text summary (async-safe)
            assets_dir = str(Path(nb_path).parent / "assets")
            try:
                text_summary = await utils._sanitize_outputs_async(
                    exec_data.get("outputs", []), assets_dir
                )
            except Exception as e:
                logger.warning(f"sanitize_outputs failed: {e}")
                text_summary = '{"llm_summary": "", "raw_outputs": []}'

            # Preserve linearity warning if it was set
            linearity_warning = (
                exec_data.get("text_summary", "")
                if isinstance(exec_data.get("text_summary"), str)
                else ""
            )
            if linearity_warning:
                # Prepend linearity warning to the sanitized output
                text_summary = linearity_warning + text_summary

            exec_data["text_summary"] = text_summary
            # Debug: log finalizer summary lengths for observability during tests
            try:
                logger.info(
                    f"Finalize exec {exec_data.get('id')} text_summary len: {len(text_summary)}"
                )
            except Exception:
                pass

            # 2. Get Cell content for content hashing
            abs_path = str(Path(nb_path).resolve())
            execution_hash = None

            # Some internal/server-side helper executions (e.g. variable manifest refresh)
            # use cell_index = -1 to indicate "not associated with a notebook cell".
            # In that case, skip notebook hashing/metadata injection and never attempt disk writes.
            cell_index = exec_data.get("cell_index", None)
            if cell_index is None or cell_index < 0:
                cell_index = None

            try:
                if cell_index is not None:
                    # Load notebook to get Cell info
                    with open(nb_path, "r", encoding="utf-8") as f:
                        nb = nbformat.read(f, as_version=4)

                    # Verify index is valid
                    if 0 <= cell_index < len(nb.cells):
                        cell = nb.cells[cell_index]
                        execution_hash = utils.get_cell_hash(cell.source)
                    else:
                        logger.warning(f"Cell index {cell_index} out of range")

            except Exception as e:
                logger.warning(f"Could not compute hash: {e}")

            # 3. Prepare metadata for injection into .ipynb
            metadata_update = {}
            if execution_hash:
                try:
                    env_info = self.sessions[abs_path].get("env_info", {})

                    metadata_update = {
                        "execution_hash": execution_hash,
                        "execution_timestamp": datetime.datetime.now().isoformat(),
                        "kernel_env_name": env_info.get("env_name", "unknown"),
                        "agent_run_id": str(uuid.uuid4()),
                    }
                except Exception as e:
                    logger.warning(f"Failed to prepare metadata: {e}")

            # 4. Write to Notebook File WITH metadata injection
            # If there are active WebSocket clients, avoid writing to disk to
            # prevent file watcher conflicts in editors (e.g. VS Code).
            active_clients = 0
            if hasattr(self, "connection_manager") and self.connection_manager:
                try:
                    active_clients = len(self.connection_manager.active_connections)
                except Exception:
                    active_clients = 0

            if active_clients > 0:
                logger.info(
                    f"Skipping disk write for {nb_path} (clients connected={active_clients}). Updates were broadcasted to clients."
                )
            else:
                # Only persist outputs back into the notebook when this execution maps to a real cell.
                if cell_index is not None:
                    notebook.save_cell_execution(
                        nb_path,
                        cell_index,
                        exec_data.get("outputs", []),
                        exec_data.get("execution_count"),
                        metadata_update=metadata_update if metadata_update else None,
                    )
        except Exception as e:
            exec_data["status"] = "failed_save"
            exec_data["error"] = str(e)
            logger.error(f"Failed to finalize execution: {e}")

    async def execute_cell_async(
        self, nb_path: str, cell_index: int, code: str, exec_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Submits execution to the queue and returns an ID immediately.

        [SECURITY] Implements backpressure: raises RuntimeError if queue is full.
        This prevents DoS attacks from flooding the server with execution requests.

        Returns:
            exec_id (str): Unique execution identifier for tracking status
            None: If kernel is not running

        Raises:
            RuntimeError: If execution queue is full (backpressure)
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return None

        session = self.sessions[abs_path]

        # HEAL CHECK: If this is an inspection or system tool, ensure helper exists
        # If the kernel restarted, we might not know, so we ensure it's available.
        if "_mcp_inspect" in code and "def _mcp_inspect" not in code:
            code = INSPECT_HELPER_CODE + "\n" + code

        # Generate execution ID if not provided
        if not exec_id:
            exec_id = str(uuid.uuid4())

        # [SECURITY] Check if queue is full (backpressure)
        if session["execution_queue"].full():
            queue_size = session["execution_queue"].qsize()
            max_size = session["execution_queue"].maxsize
            logger.error(
                f"[BACKPRESSURE] Execution queue full for {nb_path} "
                f"({queue_size}/{max_size} items). Rejecting execution request."
            )
            raise RuntimeError(
                f"Execution queue is full ({queue_size}/{max_size} pending executions). "
                "Please wait for current executions to complete before submitting more. "
                "This prevents server resource exhaustion."
            )

        # Track as queued immediately (before atomic queue operation)
        session["queued_executions"][exec_id] = {
            "cell_index": cell_index,
            "code": code,
            "status": "queued",
            "queued_time": asyncio.get_event_loop().time(),
        }

        # Create execution request
        exec_request = {"cell_index": cell_index, "code": code, "exec_id": exec_id}

        # [SECURITY] Atomic backpressure check using put_nowait (prevents race condition)
        try:
            session["execution_queue"].put_nowait(exec_request)
        except asyncio.QueueFull:
            # Remove from queued_executions since we failed to enqueue
            del session["queued_executions"][exec_id]

            queue_size = session["execution_queue"].qsize()
            max_size = session["execution_queue"].maxsize
            logger.error(
                f"[BACKPRESSURE] Execution queue full for {nb_path} "
                f"({queue_size}/{max_size} items). Rejecting execution request."
            )
            raise RuntimeError(
                f"Execution queue is full ({queue_size}/{max_size} pending executions). "
                "Please wait for current executions to complete before submitting more. "
                "This prevents server resource exhaustion."
            )

        logger.debug(f"Queued execution {exec_id} for {nb_path} cell {cell_index}")
        return exec_id

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
        """Get the status of an execution by its ID."""
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return {"status": "error", "message": "Kernel not found"}

        session = self.sessions[abs_path]

        # Check if still in queue (not started processing yet)
        if exec_id in session.get("queued_executions", {}):
            queued_data = session["queued_executions"][exec_id]
            return {
                "status": "queued",
                "output": "",
                "cell_index": queued_data.get("cell_index", -1),
                "intermediate_outputs_count": 0,
            }

        # Look for the execution by ID in active executions
        target_data = None
        for msg_id, data in session.get("executions", {}).items():
            if data.get("id") == exec_id:
                target_data = data
                break

        if not target_data:
            return {"status": "not_found", "output": ""}

        output = target_data.get("text_summary", "")
        if not output and target_data.get("status") == "completed":
            # Try to compute sanitized output if finalization hasn't populated text_summary yet
            try:
                assets_dir = str(Path(nb_path).parent / "assets")
                output = utils.sanitize_outputs(
                    target_data.get("outputs", []), assets_dir
                )
            except Exception:
                # Fallback: extract plain text from raw outputs
                collected = []
                for out in target_data.get("outputs", []):
                    if isinstance(out, dict):
                        if isinstance(out.get("text"), str):
                            collected.append(out["text"])
                        elif isinstance(out.get("data"), dict):
                            text_plain = out["data"].get("text/plain")
                            if isinstance(text_plain, str):
                                collected.append(text_plain)
                        elif isinstance(out.get("traceback"), list):
                            collected.append("\n".join(out["traceback"]))
                output = "".join(collected)

        return {
            "status": target_data.get("status", "unknown"),
            "output": output,
            "intermediate_outputs_count": len(target_data.get("outputs", [])),
        }

    def is_kernel_busy(self, nb_path: str) -> bool:
        """
        Check if the kernel is currently busy executing code.

        Returns True if there are any executions with 'running' or 'queued' status.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return False

        session = self.sessions[abs_path]

        # Check queued executions
        if session.get("queued_executions"):
            return True

        # Check active executions for running status
        for msg_id, data in session.get("executions", {}).items():
            if data.get("status") in ["running", "queued"]:
                return True

        return False

    async def _run_and_wait_internal(self, nb_path: str, code: str):
        """Internal helper to run code via the async system and wait for result."""
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return "Error: No kernel."

        # We use cell_index -1 to denote internal/temporary
        exec_id = await self.execute_cell_async(nb_path, -1, code)
        if not exec_id:
            return "Error starting internal execution."

        # Wait loop
        for _ in range(60):  # Write max wait 30s (60 * 0.5)
            await asyncio.sleep(0.5)
            status = self.get_execution_status(nb_path, exec_id)
            if status["status"] in ["completed", "error"]:
                # Give a moment for finalization to set text_summary
                # (status becomes 'completed' before finalize_callback finishes)
                if not status.get("output"):
                    await asyncio.sleep(0.2)
                    status = self.get_execution_status(nb_path, exec_id)
                return status["output"]

        return "Error: Timeout waiting for internal command."

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
                from src.asset_manager import prune_unused_assets

                cleanup_result = prune_unused_assets(abs_path, dry_run=False)
                logger.info(
                    f"[ASSET CLEANUP] Prune result: {cleanup_result.get('message', 'completed')}"
                )
            except Exception as e:
                logger.warning(f"[ASSET CLEANUP] Failed: {e}")

        # Cancel all background tasks
        tasks_to_cancel = [
            ("queue_processor_task", True),  # Needs shutdown signal
            ("listener_task", False),
            ("stdin_listener_task", False),
            ("health_check_task", False),
        ]

        for task_name, needs_signal in tasks_to_cancel:
            if session.get(task_name):
                if needs_signal and task_name == "queue_processor_task":
                    await session["execution_queue"].put(None)  # Shutdown signal

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
        # Remove scoped workspace if created for Docker isolation
        scoped_dir = session.get("scoped_workdir")
        if scoped_dir:
            try:
                import shutil

                shutil.rmtree(scoped_dir)
                logger.info(f"[SCOPED MOUNTS] Removed scoped workspace: {scoped_dir}")
            except Exception as e:
                logger.warning(f"Failed to remove scoped workspace {scoped_dir}: {e}")

        del self.sessions[abs_path]
        self.state_manager.remove_session(abs_path)

        return "Kernel shutdown."
    async def cancel_execution(self, nb_path: str, exec_id: Optional[str] = None):
        """
        [P1 FIX] Multi-stage cancellation with escalation.

        Implements graceful degradation:
        1. SIGINT (KeyboardInterrupt) - wait 3 seconds
        2. SIGTERM (terminate) - wait 2 seconds
        3. SIGKILL + restart (nuclear option)

        This prevents zombie computations from C-extensions that ignore SIGINT.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return "No kernel."

        session = self.sessions[abs_path]

        # Stage 1: Send SIGINT (KeyboardInterrupt)
        try:
            await session["km"].interrupt_kernel()
            logger.info(f"[CANCEL] Stage 1: Sent SIGINT to {nb_path}")
        except Exception as e:
            logger.error(f"[CANCEL] Failed to send SIGINT: {e}")
            return f"Failed to interrupt: {e}"

        # Wait 3 seconds, checking every 0.5s
        for i in range(6):
            await asyncio.sleep(0.5)

            # Check if execution completed/cancelled
            if exec_id and exec_id in session["executions"]:
                status = session["executions"][exec_id].get("status")
                if status in ["cancelled", "error", "completed"]:
                    logger.info("[CANCEL] Stage 1 succeeded (SIGINT)")
                    return "Cancelled gracefully (SIGINT)"

            # Check kernel client responsiveness
            kc = session.get("kc")
            if kc:
                try:
                    is_alive = kc.is_alive()
                    if hasattr(is_alive, '__await__') or hasattr(is_alive, '__iter__'):
                        is_alive = await is_alive
                except Exception:
                    is_alive = False

                if not is_alive:
                    logger.warning("[CANCEL] Kernel died during interrupt")
                    return "Kernel terminated"

        # Stage 2: SIGINT failed, escalate to SIGTERM
        logger.warning("[CANCEL] Stage 1 failed, escalating to Stage 2: SIGTERM")
        kernel_process = None
        try:
            km = session["km"]
            kernel_process = _get_kernel_process(km)
            if kernel_process:
                import signal

                kernel_process.send_signal(signal.SIGTERM)
                logger.info(
                    f"[CANCEL] Stage 2: Sent SIGTERM to PID {kernel_process.pid}"
                )
        except Exception as e:
            logger.error(f"[CANCEL] Failed to send SIGTERM: {e}")

        # Wait 2 seconds
        await asyncio.sleep(2)

        # Check if kernel stopped (by checking if process is gone)
        kernel_terminated = False
        if kernel_process:
            try:
                # poll() returns None if process is still running, else return code
                kernel_terminated = kernel_process.poll() is not None
            except Exception:
                kernel_terminated = True  # Assume terminated if we can't check

        if kernel_terminated:
            # Mark any running execution as cancelled
            # Look for the execution by ID (executions are keyed by msg_id, not exec_id)
            for msg_id, data in session.get("executions", {}).items():
                if data.get("id") == exec_id or (
                    not exec_id and data.get("status") == "running"
                ):
                    data["status"] = "cancelled"
                    data["text_summary"] = "Force terminated (SIGTERM)"
                    break
            # Also check queued_executions
            if exec_id and exec_id in session.get("queued_executions", {}):
                session["queued_executions"][exec_id]["status"] = "cancelled"
            logger.info("[CANCEL] Stage 2 succeeded (SIGTERM)")
            return "Force terminated (SIGTERM)"

        # Also check kernel client
        kc = session.get("kc")
        if kc:
            try:
                is_alive = kc.is_alive()
                if hasattr(is_alive, '__await__') or hasattr(is_alive, '__iter__'):
                    is_alive = await is_alive
                if not is_alive:
                    # Mark any running execution as cancelled
                    for msg_id, data in session.get("executions", {}).items():
                        if data.get("id") == exec_id or (
                            not exec_id and data.get("status") == "running"
                        ):
                            data["status"] = "cancelled"
                            data["text_summary"] = "Force terminated (SIGTERM)"
                            break
                    if exec_id and exec_id in session.get("queued_executions", {}):
                        session["queued_executions"][exec_id]["status"] = "cancelled"
                    logger.info("[CANCEL] Stage 2 succeeded (SIGTERM via client check)")
                    return "Force terminated (SIGTERM)"
            except Exception:
                # Client check failed, assume kernel is dead
                for msg_id, data in session.get("executions", {}).items():
                    if data.get("id") == exec_id or (
                        not exec_id and data.get("status") == "running"
                    ):
                        data["status"] = "cancelled"
                        data["text_summary"] = "Force terminated (SIGTERM)"
                        break
                if exec_id and exec_id in session.get("queued_executions", {}):
                    session["queued_executions"][exec_id]["status"] = "cancelled"
                logger.info("[CANCEL] Stage 2 succeeded (SIGTERM, client unavailable)")
                return "Force terminated (SIGTERM)"

        # Stage 3: Nuclear option - SIGKILL + restart
        logger.error(
            "[CANCEL] Stage 2 failed, escalating to Stage 3: SIGKILL + restart"
        )
        try:
            km = session["km"]
            kernel_process = _get_kernel_process(km)
            if kernel_process:
                import signal

                kernel_process.send_signal(signal.SIGKILL)
                logger.info(
                    f"[CANCEL] Stage 3: Sent SIGKILL to PID {kernel_process.pid}"
                )

            # Force cleanup
            await self.stop_kernel(nb_path, cleanup_assets=False)

            # Attempt restart with state recovery
            logger.info("[CANCEL] Attempting kernel restart...")
            await self.start_kernel(nb_path)

            # Try to restore from checkpoint if available
            # [ROUND 2 AUDIT] Checkpoint auto-restore removed for security compliance
            return "Killed and restarted (state lost - re-execute cells to restore)"

        except Exception as e:
            logger.error(f"[CANCEL] Stage 3 failed: {e}")
            return f"Failed to kill and restart: {e}"

        # We manually mark the specific execution as cancelled if found (Force fallback)
        if exec_id is not None:
            for msg_id, data in session["executions"].items():
                if data["id"] == exec_id and data["status"] == "running":
                    data["status"] = "cancelled"
                    return "Kernel interrupted successfully (Marked as cancelled)."

        return "Warning: Kernel sent interrupt signal but is still busy. It may be catching KeyboardInterrupt."

    async def shutdown_all(self):
        """Kills all running kernels and cleans up persisted session files."""
        for abs_path, session in list(self.sessions.items()):
            if session.get("listener_task"):
                session["listener_task"].cancel()
            try:
                await session["km"].shutdown_kernel(now=True)
                # Remove persisted session info
                self.state_manager.remove_session(abs_path)
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
            from src.asset_manager import prune_unused_assets

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
            from src.config import load_and_validate_settings

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
        # Delegated to new KernelStateManager
        if hasattr(self, "state_manager"):
            self.state_manager.reconcile_zombies()


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
