import os
import sys
import asyncio
import uuid
import json
import logging
import nbformat
import datetime
import subprocess
import re
try:
    import dill
except ImportError:
    dill = None
from pathlib import Path
from typing import Dict, Any, Optional
from jupyter_client.manager import AsyncKernelManager
from src import notebook, utils
from src.cell_id_manager import get_cell_id_at_index
from src.observability import get_logger, get_tracer

# Configure logging
logger = get_logger()
tracer = get_tracer(__name__)

# [SECURITY] Safe Inspection Helper
INSPECT_HELPER_CODE = """
def _mcp_inspect(var_name):
    import builtins
    import sys
    
    # Safe lookup: Check locals then globals
    # Note: In ipykernel, user variables are in globals()
    ns = globals()
    if var_name not in ns:
        return f"Variable '{var_name}' not found."
    
    obj = ns[var_name]
    
    try:
        t_name = type(obj).__name__
        output = [f"### Type: {t_name}"]
        
        # Check for pandas/numpy without importing if not already imported
        is_pd_df = 'pandas' in sys.modules and isinstance(obj, sys.modules['pandas'].DataFrame)
        is_pd_series = 'pandas' in sys.modules and isinstance(obj, sys.modules['pandas'].Series)
        is_numpy = 'numpy' in sys.modules and hasattr(obj, 'shape') and hasattr(obj, 'dtype')
        
        # Safe Primitives
        if isinstance(obj, (int, float, bool, str, bytes, type(None))):
             output.append(f"- Value: {str(obj)[:500]}")

        elif is_pd_df:
            output.append(f"- Shape: {obj.shape}")
            output.append(f"- Columns: {list(obj.columns)}")
            output.append("\\n#### Head (3 rows):")
            # to_markdown requires tabulate, fallback to string if fails
            try:
                output.append(obj.head(3).to_markdown(index=False))
            except:
                output.append(str(obj.head(3)))
            
        elif is_pd_series:
            output.append(f"- Length: {len(obj)}")
            try:
                output.append(obj.head(3).to_markdown())
            except:
                output.append(str(obj.head(3)))
            
        elif is_numpy:
            output.append(f"- Shape: {obj.shape}")
            output.append(f"- Dtype: {obj.dtype}")
            
        elif isinstance(obj, (list, tuple, set)):
             output.append(f"- Length: {len(obj)}")
             output.append(f"- Sample: {str(list(obj)[:3])}")
             
        elif isinstance(obj, dict):
             output.append(f"- Keys ({len(obj)}): {list(obj.keys())[:5]}")
             
        elif hasattr(obj, '__dict__'):
             output.append(f"- Attributes: {list(obj.__dict__.keys())[:5]}")
             
        return "\\n".join(output)
            
    except Exception as e:
        return f"Error inspecting '{var_name}': {str(e)}"
"""

# START: Moved to environment.py but kept for backward compatibility if needed
# Better to import it
from src.environment import get_activated_env_vars as _get_activated_env_vars
# END

import hmac
import secrets

def get_or_create_secret():
    """
    [SECURITY FIX] Get or create persistent session secret.
    
    The secret is stored in ~/.mcp-jupyter/secret.key with 0o600 permissions.
    This ensures checkpoints remain valid across server restarts.
    """
    secret_path = Path.home() / ".mcp-jupyter" / "secret.key"
    
    if secret_path.exists():
        return secret_path.read_bytes()
    
    # Generate new secret
    secret = secrets.token_bytes(32)
    
    # Create directory with restricted permissions
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write file
    with open(secret_path, 'wb') as f:
        f.write(secret)
    
    # Set permissions to user-only read/write (chmod 600)
    os.chmod(secret_path, 0o600)
    
    return secret

# Generate a persistent session secret used to sign local checkpoints.
# This ensures checkpoints remain valid across server restarts.
SESSION_SECRET = get_or_create_secret()

class SessionManager:
    def __init__(self, default_execution_timeout: int = 300, input_request_timeout: int = 60):
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
        self.max_concurrent_kernels = int(os.environ.get('MCP_MAX_KERNELS', '10'))
        logger.info(f"Max concurrent kernels: {self.max_concurrent_kernels}")
        
        # Reference to MCP server for notifications
        self.mcp_server = None
        self.server_session = None
        
        # Session persistence directory
        self.persistence_dir = Path.home() / ".mcp-jupyter" / "sessions"
        self.persistence_dir.mkdir(parents=True, exist_ok=True)
        
        # [REAPER FIX] Track file locks for sessions to prevent fratricide
        self._session_locks = {}

        # [REAPER] Start the background reaper task
        self._reaper_task = asyncio.create_task(self._reaper_loop())
        
        # [PHASE 2.3] Start asset cleanup task
        self._asset_cleanup_task = asyncio.create_task(self._asset_cleanup_loop())
        
    def set_mcp_server(self, mcp_server):
        """Set the MCP server instance to enable notifications."""
        self.mcp_server = mcp_server
        # [BROADCASTER] Optional connection manager for multi-user support
        self.connection_manager = None

    def register_session(self, session):
        """Register a client session for sending notifications."""
        if not hasattr(self, 'active_sessions'):
            self.active_sessions = set()
        
        self.active_sessions.add(session)
        logger.info(f"Registered new client session. Total active: {len(self.active_sessions)}")

    async def _send_notification(self, method: str, params: Any):
        """Helper to send notifications via available channels (Broadcast)."""
        
        # 1. Prefer the WebSocket Connection Manager (Multi-User)
        if hasattr(self, 'connection_manager') and self.connection_manager:
            msg = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params
            }
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
        """
        logger.info(f"Starting Asset Cleanup task (scan interval: {interval}s)")
        max_age_hours = int(os.environ.get('MCP_ASSET_MAX_AGE_HOURS', '24'))
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
                                logger.debug(f"[ASSET CLEANUP] Deleted old asset: {asset_file.name} (age: {file_age/3600:.1f}h)")
                        except Exception as e:
                            logger.warning(f"[ASSET CLEANUP] Failed to delete {asset_file.name}: {e}")
                
                if deleted_count > 0:
                    logger.info(f"[ASSET CLEANUP] Deleted {deleted_count} old assets (>{max_age_hours}h)")
                
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("Asset cleanup task cancelled.")
                break
            except Exception as e:
                logger.error(f"[ASSET CLEANUP] Unhandled error: {e}")
                await asyncio.sleep(interval)
    
    async def _reaper_loop(self, interval: int = 60):
        """
        [REAPER] Periodically scans for and cleans up zombie kernels from dead server processes.
        """
        logger.info(f"Starting Grim Reaper task (scan interval: {interval}s)")
        try:
            import psutil
        except ImportError:
            logger.warning("[REAPER] psutil not installed. Zombie process reaping is disabled.")
            return

        await asyncio.sleep(interval) # Initial delay

        while True:
            try:
                current_pid = os.getpid()
                current_proc = psutil.Process(current_pid)
                current_create_time = current_proc.create_time()

                # [REAPER FIX] Use file locking to detect dead sessions
                for lock_file in self.persistence_dir.glob("session_*.lock"):
                    try:
                        # Try to acquire the lock
                        # If successful, the owning process is dead
                        try:
                            import fcntl
                            with open(lock_file, 'r+') as f:
                                try:
                                    fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                    # Lock acquired! This means the original process is dead
                                    is_zombie = True
                                except IOError:
                                    # Lock is held by another living process
                                    is_zombie = False
                                    continue
                        except ImportError:
                            # Windows fallback
                            try:
                                import portalocker
                                with open(lock_file, 'r+') as f:
                                    try:
                                        portalocker.lock(f, portalocker.LOCK_EX | portalocker.LOCK_NB)
                                        is_zombie = True
                                    except portalocker.LockException:
                                        is_zombie = False
                                        continue
                            except (ImportError, Exception):
                                # No locking available - skip this lock file
                                continue
                        
                        if is_zombie:
                            # Find corresponding session JSON file
                            session_hash = lock_file.stem.replace('session_', '')
                            session_file = self.persistence_dir / f"session_{session_hash}.json"
                            
                            if session_file.exists():
                                with open(session_file, 'r') as f:
                                    session_data = json.load(f)
                                
                                server_pid = session_data.get('server_pid')
                                kernel_pid = session_data.get('pid')
                                saved_create_time = session_data.get('pid_create_time')
                                
                                logger.warning(f"[REAPER] Found orphan session from dead server PID {server_pid} for kernel PID {kernel_pid}.")
                                
                                # Kill the zombie kernel - BUT ONLY if create_time matches
                                if kernel_pid and psutil.pid_exists(kernel_pid):
                                    try:
                                        proc = psutil.Process(kernel_pid)
                                        # [REAPER FIX] Verify it's actually our process by checking creation time
                                        if saved_create_time is None or proc.create_time() == saved_create_time:
                                            proc_name = proc.name()
                                            proc.kill()
                                            logger.info(f"[REAPER] Killed zombie kernel process {kernel_pid} ({proc_name}).")
                                        else:
                                            logger.warning(f"[REAPER] PID {kernel_pid} was reused by OS. Not killing (create_time mismatch).")
                                    except psutil.NoSuchProcess:
                                        pass
                                    except Exception as e:
                                        logger.error(f"[REAPER] Error killing zombie kernel {kernel_pid}: {e}")
                                
                                # Clean up files
                                session_file.unlink()
                                logger.info(f"[REAPER] Cleaned up orphan session file: {session_file.name}")
                            
                            # Delete the lock file
                            lock_file.unlink()
                            logger.info(f"[REAPER] Cleaned up lock file: {lock_file.name}")
                    
                    except Exception as e:
                        logger.warning(f"[REAPER] Error processing lock file {lock_file.name}: {e}")
                
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                logger.info("Reaper task cancelled.")
                break
            except Exception as e:
                logger.error(f"[REAPER] Unhandled error in reaper loop: {e}")
                await asyncio.sleep(interval) # Avoid fast crash loop
    
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
                
                kc = session.get('kc')
                if not kc:
                    break
                
                # Check if kernel is alive via heartbeat
                if not kc.is_alive():
                    logger.error(f"[HEALTH CHECK] Kernel {nb_path} died. Attempting restart...")
                    try:
                        await self.restart_kernel(nb_path)
                    except Exception as e:
                        logger.error(f"[HEALTH CHECK] Failed to restart kernel: {e}")
                        break
                else:
                    # Optional: Send lightweight info request for deeper check
                    try:
                        await asyncio.wait_for(kc.kernel_info(), timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"[HEALTH CHECK] Kernel {nb_path} unresponsive to info request")
                    except Exception as e:
                        logger.warning(f"[HEALTH CHECK] Error checking kernel: {e}")
                
                await asyncio.sleep(check_interval)
                
            except asyncio.CancelledError:
                logger.info(f"[HEALTH CHECK] Task cancelled for {nb_path}")
                break
            except Exception as e:
                logger.error(f"[HEALTH CHECK] Unhandled error: {e}")
                await asyncio.sleep(check_interval)
    
    def _persist_session_info(self, nb_path: str, connection_file: str, pid: Any, env_info: Dict):
        """
        Save session info to disk to prevent zombie kernels after server restart.
        
        Stores:
        - Connection file path (for reconnecting to kernel)
        - Process ID (for checking if kernel still alive)
        - Environment info (for proper cleanup)
        """
        try:
            # Use notebook path hash as filename to handle special chars
            import hashlib
            import psutil
            path_hash = hashlib.md5(nb_path.encode()).hexdigest()
            session_file = self.persistence_dir / f"session_{path_hash}.json"
            
            current_proc = psutil.Process(os.getpid())
            
            # [REAPER FIX] Track kernel process creation time to prevent killing recycled PIDs
            kernel_create_time = None
            if pid and isinstance(pid, int):
                try:
                    kernel_proc = psutil.Process(pid)
                    kernel_create_time = kernel_proc.create_time()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            session_data = {
                "notebook_path": nb_path,
                "connection_file": connection_file,
                "pid": pid if isinstance(pid, int) else None,
                "pid_create_time": kernel_create_time,  # [REAPER FIX] Track kernel process creation time
                "server_pid": os.getpid(),  # [REAPER FIX] Track which server owns this kernel
                "server_create_time": current_proc.create_time(), # [REAPER FIX] And its start time
                "env_info": env_info,
                "created_at": datetime.datetime.now().isoformat()
            }
            
            with open(session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            
            # [REAPER FIX] Create and hold a lock file for this session
            # This lock proves the server process is alive
            lock_file = self.persistence_dir / f"session_{path_hash}.lock"
            try:
                # Try to import fcntl (Unix) or use fallback
                try:
                    import fcntl
                    lock_fd = open(lock_file, 'w')
                    # Acquire non-blocking exclusive lock
                    fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._session_locks[nb_path] = lock_fd
                    logger.info(f"Acquired file lock for session {nb_path}")
                except ImportError:
                    # Windows fallback - use portalocker if available, or just create the file
                    try:
                        import portalocker
                        lock_fd = open(lock_file, 'w')
                        portalocker.lock(lock_fd, portalocker.LOCK_EX | portalocker.LOCK_NB)
                        self._session_locks[nb_path] = lock_fd
                        logger.info(f"Acquired file lock for session {nb_path} (portalocker)")
                    except (ImportError, Exception):
                        # Fallback: just create the lock file without locking
                        # This provides basic protection but not foolproof
                        lock_fd = open(lock_file, 'w')
                        lock_fd.write(str(os.getpid()))
                        lock_fd.flush()
                        self._session_locks[nb_path] = lock_fd
                        logger.warning(f"Created lock file without fcntl/portalocker for {nb_path}")
            except IOError as e:
                logger.error(f"Could not acquire lock on session file: {e}")
            
            logger.info(f"Persisted session info for {nb_path} (PID: {pid})")
        except Exception as e:
            logger.warning(f"Failed to persist session info: {e}")
    
    def _remove_persisted_session(self, nb_path: str):
        """Remove persisted session info when kernel is shut down."""
        try:
            import hashlib
            path_hash = hashlib.md5(nb_path.encode()).hexdigest()
            session_file = self.persistence_dir / f"session_{path_hash}.json"
            lock_file = self.persistence_dir / f"session_{path_hash}.lock"
            
            if session_file.exists():
                session_file.unlink()
                logger.info(f"Removed persisted session for {nb_path}")
            
            # [REAPER FIX] Close and remove lock file
            if nb_path in self._session_locks:
                try:
                    self._session_locks[nb_path].close()
                    del self._session_locks[nb_path]
                except Exception as e:
                    logger.warning(f"Error closing lock file: {e}")
            
            if lock_file.exists():
                lock_file.unlink()
                logger.info(f"Removed lock file for {nb_path}")
        except Exception as e:
            logger.warning(f"Failed to remove persisted session: {e}")
    
    async def restore_persisted_sessions(self):
        """
        Attempt to restore sessions from disk on server startup.
        
        Checks if kernel PIDs are still alive and reconnects if possible.
        Cleans up stale session files for dead kernels.
        """
        restored_count = 0
        cleaned_count = 0
        
        for session_file in self.persistence_dir.glob("session_*.json"):
            try:
                with open(session_file, 'r') as f:
                    session_data = json.load(f)
                
                nb_path = session_data['notebook_path']
                pid = session_data['pid']
                connection_file = session_data['connection_file']
                saved_create_time = session_data.get('pid_create_time')
                
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
                            if saved_create_time is None or proc.create_time() == saved_create_time:
                                pid_valid = True
                            else:
                                logger.warning(f"PID {pid} was reused. Skipping restoration.")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    
                    if pid_valid and Path(connection_file).exists():
                        # Try to reconnect to existing kernel
                        logger.info(f"Attempting to restore session for {nb_path} (PID: {pid})")
                        
                        try:
                            # Create kernel manager from existing connection file
                            km = AsyncKernelManager(connection_file=connection_file)
                            km.load_connection_file()
                            
                            # Create client and connect
                            kc = km.client()
                            kc.start_channels()
                            
                            # Test if kernel is responsive
                            await asyncio.wait_for(kc.wait_for_ready(timeout=10), timeout=15)
                            
                            # Get notebook directory for CWD
                            notebook_dir = str(Path(nb_path).parent.resolve())
                            
                            # Restore session structure
                            abs_path = str(Path(nb_path).resolve())
                            session_dict = {
                                'km': km,
                                'kc': kc,
                                'cwd': notebook_dir,
                                'listener_task': None,
                                'executions': {},
                                'queued_executions': {},
                                'execution_queue': asyncio.Queue(),
                                'execution_counter': 0,
                                'stop_on_error': False,
                                'exec_lock': asyncio.Lock(), # [RACE CONDITION FIX]
                                'env_info': session_data.get('env_info', {
                                    'python_path': 'unknown',
                                    'env_name': 'unknown',
                                    'start_time': session_data.get('created_at', 'unknown')
                                })
                            }
                            
                            # Start background tasks
                            session_dict['listener_task'] = asyncio.create_task(
                                self._kernel_listener(abs_path, kc, session_dict['executions'])
                            )
                            session_dict['queue_processor_task'] = asyncio.create_task(
                                self._queue_processor(abs_path, session_dict)
                            )
                            
                            self.sessions[abs_path] = session_dict
                            restored_count += 1
                            logger.info(f"Successfully restored session for {nb_path}")
                            
                        except Exception as reconnect_error:
                            logger.warning(f"Failed to reconnect to kernel PID {pid}: {reconnect_error}")
                            # Clean up the stale session file
                            session_file.unlink()
                            cleaned_count += 1
                    else:
                        # Kernel is dead or connection file missing, clean up
                        if not psutil.pid_exists(pid):
                            logger.info(f"Kernel PID {pid} for {nb_path} is dead, cleaning up")
                        else:
                            # [GRIM REAPER] If PID exists but we can't connect/verify, kill it to prevent zombies
                            logger.warning(f"Kernel PID {pid} exists but connection file is missing/invalid. Killing zombie process.")
                            try:
                                proc = psutil.Process(pid)
                                proc.terminate()
                                # Give it a moment to die gracefully
                                try:
                                    proc.wait(timeout=2.0)
                                except psutil.TimeoutExpired:
                                    proc.kill()
                            except Exception as cleanup_error:
                                logger.warning(f"Failed to kill zombie kernel {pid}: {cleanup_error}")
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
        if os.name == 'nt':
            candidate = root / "Scripts" / "python.exe"
            if candidate.exists(): return str(candidate)
            
        # Linux/Mac Check
        candidate = root / "bin" / "python"
        if candidate.exists(): return str(candidate)
        
        # Fallback
        return sys.executable
    
    def _validate_mount_path(self, project_root: Path) -> Path:
        """
        [FIX #5] Validate Docker mount path to prevent path traversal attacks.
        
        Ensures the mount path is within allowed directories and doesn't
        escape via symlinks or .. traversal.
        """
        resolved_root = project_root.resolve()
        
        # Define allowed base path (configurable via environment)
        allowed_base = Path(os.environ.get("MCP_ALLOWED_ROOT", Path.home())).resolve()
        
        # Containment check
        try:
            resolved_root.relative_to(allowed_base)
        except ValueError:
            raise ValueError(
                f"Security Violation: Cannot mount path {resolved_root} "
                f"outside of allowed base {allowed_base}. "
                f"Set MCP_ALLOWED_ROOT environment variable to change this."
            )
        
        return resolved_root

    async def start_kernel(self, nb_path: str, venv_path: Optional[str] = None, docker_image: Optional[str] = None, timeout: Optional[int] = None, agent_id: Optional[str] = None):
        """
        Start a Jupyter kernel for a notebook.
        
        Args:
            nb_path: Path to the notebook file
            venv_path: Optional path to Python environment (venv/conda)
            docker_image: Optional docker image to run kernel safely inside
            timeout: Execution timeout in seconds (default: 300)
        """
        abs_path = str(Path(nb_path).resolve())
        # Set session timeout
        execution_timeout = timeout if timeout is not None else self.default_execution_timeout

        # Check for Dill (UX Fix)
        if not dill:
            logger.warning("['dill' is missing] State checkpointing/recovery will not work. Install 'dill' in your server environment.")

        # Determine the Notebook's directory to set as CWD
        notebook_dir = str(Path(nb_path).parent.resolve())

        # If an agent_id is provided, create a per-agent subdirectory to isolate relative file access
        if agent_id:
            # Sanitize agent_id for use in filesystem
            safe_agent = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(agent_id))
            agent_dir = Path(notebook_dir) / f"agent_{safe_agent}"
            agent_dir.mkdir(parents=True, exist_ok=True)
            notebook_dir = str(agent_dir.resolve())
            logger.info(f"Agent CWD isolation enabled for agent '{agent_id}': {notebook_dir}")

        if abs_path in self.sessions: 
            return f"Kernel already running for {abs_path}"
        
        # [PHASE 3.2] Check kernel limit
        if len(self.sessions) >= self.max_concurrent_kernels:
            oldest_session = min(self.sessions.items(), key=lambda x: x[1].get('start_time', 0))
            logger.warning(f"Kernel limit ({self.max_concurrent_kernels}) reached. Consider stopping {oldest_session[0]}")
            return json.dumps({
                "error": f"Maximum concurrent kernels ({self.max_concurrent_kernels}) reached",
                "suggestion": f"Stop an existing kernel first. Oldest: {oldest_session[0]}",
                "active_kernels": list(self.sessions.keys())
            })
        
        km = AsyncKernelManager()
        
        if docker_image:
             # [PHASE 4: Docker Support]
             # Strategy: Use docker run to launch the kernel
             # We must mount:
             # 1. The workspace (so imports work)
             # 2. The connection file (so we can talk to it)
             
             # Locate workspace root for proper relative imports
             project_root = utils.get_project_root(Path(notebook_dir))
             
             # [FIX #5] Validate mount path to prevent path traversal
             project_root = self._validate_mount_path(project_root)
             
             mount_source = str(project_root)
             mount_target = "/workspace"
             
             # [SECURITY] Implement "Sandbox Subdirectory" pattern
             # Mount source code read-only, but provide a read-write sandbox for outputs.
             sandbox_dir = project_root / ".mcp_sandbox"
             sandbox_dir.mkdir(exist_ok=True)
             
             # Calculate CWD inside container, which is now the sandbox
             container_cwd = "/workspace/sandbox"
             
             # Construct Docker Command
             uid_args = ['-u', str(os.getuid())] if os.name != 'nt' else ['-u', '1000']
             cmd = [
                 'docker', 'run', 
                 '--rm',                     # Cleanup container on exit
                 '-i',                       # Interactive (keeps stdin open)
                 '--init',                   # Ensure PID 1 forwards signals to children
                 '--network', 'none',        # [SECURITY] Disable networking
                 '--security-opt', 'no-new-privileges',
                 '--read-only',
                 '--tmpfs', '/tmp:rw,noexec,nosuid,size=1g',
                 # Mount source code read-only for reference
                 '-v', f'{project_root}:/workspace/source:ro',
                 # Mount sandbox read-write for assets/outputs
                 '-v', f'{sandbox_dir}:/workspace/sandbox:rw',
                 '-v', '{connection_file}:/kernel.json:ro',
                 '-w', container_cwd,        # CWD is the sandbox
             ] + uid_args + [
                 docker_image,
                 'python', '-m', 'ipykernel_launcher', '-f', '/kernel.json'
             ]

             # Resource limit for Docker: cap memory to 4GB to avoid noisy neighbor OOMs
             cmd.insert(2, '--memory')
             cmd.insert(3, '4g')
             
             km.kernel_cmd = cmd
             logger.info(f"Configured Docker kernel: {cmd}")
             
             # We explicitly do NOT activate local envs if using Docker
             # Docker image is the environment
             kernel_env = {} 
             
             # Set metadata for session tracking
             py_exe = "python" # Inside container
             env_name = f"docker:{docker_image}"
        
        else:
            # 1. Handle Environment (Local)
            py_exe = sys.executable
            env_name = "system"
            kernel_env = os.environ.copy()  # Default: inherit current environment

            # Resource limits: on POSIX, prefer to use `prlimit` if available to bound address space
            try:
                import shutil
                prlimit_prefix = ['prlimit', '--as=4294967296'] if (os.name != 'nt' and shutil.which('prlimit')) else []
            except Exception:
                prlimit_prefix = []

            if venv_path:
                venv_path_obj = Path(venv_path).resolve()
                is_conda = (venv_path_obj / "conda-meta").exists()

                py_exe = self.get_python_path(venv_path)
                env_name = venv_path_obj.name

                # Validation
                if not is_conda and not str(py_exe).lower().startswith(str(venv_path_obj).lower()):
                    return f"Error: Could not find python executable in {venv_path}"

                if is_conda:
                    # Prefer resolving env vars and running the env's python directly.
                    try:
                        resolved_env = _get_activated_env_vars(venv_path, py_exe)
                    except Exception:
                        resolved_env = None

                    if resolved_env and 'CONDA_PREFIX' in resolved_env:
                        kernel_env = resolved_env
                        cmd = [py_exe, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
                        km.kernel_cmd = (prlimit_prefix + cmd) if prlimit_prefix else cmd
                        logger.info(f"Configured Conda kernel by invoking env python: {km.kernel_cmd}")
                    else:
                        logger.warning("Could not resolve conda env activation. Falling back to 'conda run' (interrupts may be unreliable).")
                        cmd = [
                            'conda', 'run', 
                            '-p', str(venv_path_obj), 
                            '--no-capture-output', 
                            'python', '-m', 'ipykernel_launcher', 
                            '-f', '{connection_file}'
                        ]
                        km.kernel_cmd = (prlimit_prefix + cmd) if prlimit_prefix else cmd
                else:
                    # Standard Venv: get activated env or fall back
                    kernel_env = _get_activated_env_vars(venv_path, py_exe) or os.environ.copy()
                    bin_dir = str(Path(py_exe).parent)
                    kernel_env['PATH'] = f"{bin_dir}{os.pathsep}{kernel_env.get('PATH', '')}"
                    cmd = [py_exe, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
                    km.kernel_cmd = (prlimit_prefix + cmd) if prlimit_prefix else cmd
            else:
                # No venv: default system Python kernel command
                cmd = [py_exe, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
                km.kernel_cmd = (prlimit_prefix + cmd) if prlimit_prefix else cmd

        # [CRUCIBLE] Resource Limits: if not using Docker, ensure prlimit is prepended when available
        try:
            import shutil
            if sys.platform != 'win32' and not docker_image and shutil.which('prlimit'):
                # Avoid double-prepending
                if not (isinstance(km.kernel_cmd, list) and km.kernel_cmd and km.kernel_cmd[0] == 'prlimit'):
                    from src.config import settings
                    limit_bytes = int(getattr(settings, 'MCP_MEMORY_LIMIT_BYTES', 8 * 1024**3))
                    km.kernel_cmd = ['prlimit', f'--as={limit_bytes}'] + (km.kernel_cmd if isinstance(km.kernel_cmd, list) else [km.kernel_cmd])
                    logger.info(f"resource_limits_applied limit={limit_bytes}")
        except Exception:
            # Non-fatal: log and continue
            logger.warning("prlimit_check_failed")

        # 2. Start Kernel with Correct CWD and Environment (wrapped in try/except to ensure clean shutdown)
        try:
            await km.start_kernel(cwd=notebook_dir, env=kernel_env)
            kc = km.client()
            kc.start_channels()
            try:
                await kc.wait_for_ready(timeout=120)
            except Exception as e:
                if hasattr(km, 'has_kernel') and km.has_kernel:
                    try:
                        await km.shutdown_kernel()
                    except Exception:
                        pass
                raise RuntimeError(f"Kernel failed to start: {str(e)}")
        except Exception as e:
            if hasattr(km, 'has_kernel') and km.has_kernel:
                try:
                    await km.shutdown_kernel()
                except Exception:
                    pass
            raise RuntimeError(f"Kernel failed to start: {str(e)}")

        # 3. Inject autoreload and visualization configuration immediately after kernel ready
        # Only inject Python-specific helpers when the kernel is actually Python
        kernel_name = getattr(km, 'kernel_name', '') or ''
        is_python_kernel = 'python' in kernel_name.lower() if kernel_name else True

        if is_python_kernel:
            # Execute startup setup (fire-and-forget for reliability)
            startup_code = f'''
%load_ext autoreload
%autoreload 2

import sys
import json
import traceback

# [STDIN ENABLED] MCP handles input() requests via stdin channel
# Interactive input is now supported via MCP notifications

# [SECURITY] Safe Inspection Helper
{INSPECT_HELPER_CODE}

# [PHASE 4: Smart Error Recovery]
# Inject a custom exception handler to provide context-aware error reports
def _mcp_handler(shell, etype, value, tb, tb_offset=None, **kwargs):
    # Print standard traceback
    if hasattr(sys, 'last_type'):
        del sys.last_type
    if hasattr(sys, 'last_value'):
        del sys.last_value
    if hasattr(sys, 'last_traceback'):
        del sys.last_traceback
        
    traceback.print_exception(etype, value, tb)
    
    # Generate sidecar JSON
    try:
        error_context = {{
            "error": str(value),
            "type": etype.__name__,
            "suggestion": "Check your inputs."
        }}
        sidecar_msg = f"\\n__MCP_ERROR_CONTEXT_START__\\n{{json.dumps(error_context)}}\\n__MCP_ERROR_CONTEXT_END__\\n"
        sys.stderr.write(sidecar_msg)
        sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"Error in MCP Handler: {{e}}\\n")
        sys.stderr.flush()

try:
    get_ipython().set_custom_exc((Exception,), _mcp_handler)
except Exception:
    pass

# [PHASE 3.3] Force static rendering for interactive visualization libraries
# This allows AI agents to "see" plots that would otherwise be JavaScript-based
import os
try:
    import matplotlib
    matplotlib.use('Agg')  # Headless backend for matplotlib
    # Inline backend is still useful for png display
    try:
        get_ipython().run_line_magic('matplotlib', 'inline')
    except:
        pass
except ImportError:
    pass  # matplotlib not installed, skip

# Force Plotly to render as static PNG
# NOTE: Requires kaleido installed in kernel environment: pip install kaleido
try:
    import plotly
    try:
        import kaleido
        os.environ['PLOTLY_RENDERER'] = 'png'
    except ImportError:
        # Kaleido not installed - Plotly will fall back to HTML output
        # which will be sanitized to text by the asset extraction pipeline
        pass
except ImportError:
    pass  # plotly not installed, skip

# Force Bokeh to use static SVG backend
try:
    import bokeh
    os.environ['BOKEH_OUTPUT_BACKEND'] = 'svg'
except ImportError:
    pass  # bokeh not installed, skip
'''
        if is_python_kernel:
            try:
                kc.execute(startup_code, silent=True)
                # Give it a moment to take effect
                await asyncio.sleep(0.5)
                logger.info("Autoreload and visualization config sent to kernel")
                
                # Add cwd to path
                path_code = "import sys, os\nif os.getcwd() not in sys.path: sys.path.append(os.getcwd())"
                kc.execute(path_code, silent=True)
                logger.info("Path setup sent to kernel")
                
            except Exception as e:
                logger.warning(f"Failed to inject startup code: {e}")
        else:
            logger.info(f"Non-Python kernel detected ({kernel_name}). Skipping Python startup injection.")
            
        # Create session dictionary structure
        import time
        execution_queue = asyncio.Queue()
        session_data = {
            'km': km,
            'kc': kc,
            'cwd': notebook_dir,
            'listener_task': None,
            'executions': {},
            'queued_executions': {},  # Track queued executions before processing
            'execution_queue': asyncio.Queue(),
            'executed_indices': set(), # Track which cells have been run in this session
            'execution_counter': 0,
            'max_executed_index': -1,  # [SCIENTIFIC INTEGRITY] Track execution wavefront
            'stop_on_error': False,  # NEW: Default to False for backward compatibility
            'execution_timeout': execution_timeout,  # Per-session timeout
            'start_time': time.time(),  # [PHASE 3.2] Track kernel start time for resource management
            'env_info': {  # NEW: Environment provenance tracking
                'python_path': py_exe,
                'env_name': env_name,
                'start_time': datetime.datetime.now().isoformat()
            }
        }
        
        # Start the background listener
        session_data['listener_task'] = asyncio.create_task(
            self._kernel_listener(abs_path, kc, session_data['executions'])
        )

        # Start the stdin listener (Handles input() requests)
        session_data['stdin_listener_task'] = asyncio.create_task(
            self._stdin_listener(abs_path, session_data)
        )
        
        # Start the execution queue processor
        session_data['queue_processor_task'] = asyncio.create_task(
            self._queue_processor(abs_path, session_data)
        )
        
        # [FIX #4] Start health check loop for this kernel
        session_data['health_check_task'] = asyncio.create_task(
            self._health_check_loop(abs_path)
        )
        
        self.sessions[abs_path] = session_data
        
        # Safely get PID and connection file
        pid = "unknown"
        connection_file = "unknown"
        if hasattr(km, 'kernel') and km.kernel:
            pid = getattr(km.kernel, 'pid', 'unknown')
        if hasattr(km, 'connection_file'):
            connection_file = km.connection_file
        
        # Persist session info to prevent zombie kernels after server restart
        if pid != "unknown" and connection_file != "unknown":
            self._persist_session_info(abs_path, connection_file, pid, session_data['env_info'])
                 
        return f"Kernel started (PID: {pid}). CWD set to: {notebook_dir}"

    async def _kernel_listener(self, nb_path: str, kc, executions: Dict):
        """
        Background loop that drains the IOPub channel for a specific kernel.
        It routes messages to the correct execution ID based on parent_header.
        """
        logger.info(f"Starting listener for {nb_path}")
        try:
            while True:
                # Retrieve message
                msg = await kc.get_iopub_msg()
                
                # Identify which execution this belongs to
                parent_id = msg['parent_header'].get('msg_id')
                if not parent_id or parent_id not in executions:
                    # Message might be from a previous run or system status
                    continue
                
                exec_data = executions[parent_id]
                msg_type = msg['msg_type']
                content = msg['content']

                # Update State
                if msg_type == 'status':
                    exec_data['kernel_state'] = content['execution_state']
                    if content['execution_state'] == 'idle':
                        if exec_data['status'] not in ['error', 'cancelled']:
                            exec_data['status'] = 'completed'
                        
                        # [RACE CONDITION FIX] Wait for the queue processor to be ready for finalization.
                        # This ensures stop_on_error logic has a chance to run before we commit the state.
                        if 'finalization_event' in exec_data:
                            await exec_data['finalization_event'].wait()

                        # Finalize: Save to disk (async-safe)
                        try:
                            await self._finalize_execution_async(nb_path, exec_data)
                        except Exception as e:
                            logger.warning(f"Finalize execution failed: {e}")
                        
                        # Track successful execution
                        session_data = self.sessions.get(nb_path)
                        if session_data and exec_data.get('cell_index') is not None:
                             session_data['executed_indices'].add(exec_data['cell_index'])
                        
                        # [PRIORITY 2] Emit Completion Notification
                        try:
                            await self._send_notification("notebook/status", {
                                "notebook_path": nb_path,
                                "exec_id": exec_data.get('id'),
                                "status": exec_data['status']
                            })
                        except Exception as e:
                            logger.warning(f"Failed to send status notification: {e}")

                elif msg_type == 'clear_output':
                    # [PHASE 3.1] Handle progress bars and dynamic updates (tqdm, etc.)
                    # Clear the outputs list to mimic Jupyter UI behavior
                    # This prevents file size explosion from thousands of progress updates
                    wait = content.get('wait', False)
                    if not wait:
                        # Immediate clear: reset outputs but keep streaming metadata
                        exec_data['outputs'] = []
                        # Note: output_count is NOT reset - agents track cumulative index
                        # This means the agent's stream will show gaps, but that's acceptable
                        # for progress bars (they only care about the final state)

                elif msg_type in ['stream', 'display_data', 'execute_result', 'error']:
                    # Convert to nbformat output
                    output = None
                    if msg_type == 'stream':
                        output = nbformat.v4.new_output('stream', name=content['name'], text=content['text'])
                    elif msg_type == 'display_data':
                        output = nbformat.v4.new_output('display_data', data=content['data'], metadata=content['metadata'])
                    elif msg_type == 'execute_result':
                        exec_data['execution_count'] = content.get('execution_count')
                        output = nbformat.v4.new_output('execute_result', data=content['data'], metadata=content['metadata'], execution_count=content.get('execution_count'))
                    elif msg_type == 'error':
                        exec_data['status'] = 'error'
                        output = nbformat.v4.new_output('error', ename=content['ename'], evalue=content['evalue'], traceback=content['traceback'])
                    
                    if output:
                        # [PHASE 2.1] Event-Driven Outputs: Push notifications instead of polling
                        # Broadcast the raw output message immediately.
                        if self.connection_manager:
                            await self.connection_manager.broadcast({
                                "jsonrpc": "2.0",
                                "method": "notebook/output",
                                "params": {
                                    "notebook_path": nb_path,
                                    "task_id": exec_data.get('id'),
                                    "cell_index": exec_data.get('cell_index'),
                                    "output": output,
                                }
                            })

                        exec_data['outputs'].append(output)
                        # [PHASE 3.1] Update streaming metadata
                        exec_data['output_count'] = len(exec_data['outputs'])
                        exec_data['last_activity'] = asyncio.get_event_loop().time()
                        
                        # [PRIORITY 2] Emit MCP Notification (Event-Driven Architecture)
                        try:
                            await self._send_notification("notebook/output", {
                                "notebook_path": nb_path,
                                "exec_id": exec_data.get('id'),
                                "type": msg_type,
                                "content": content
                            })
                        except Exception as e:
                            # Don't crash the listener if notification fails
                            logger.warning(f"Failed to send MCP notification: {e}")

        except asyncio.CancelledError:
            logger.info(f"Listener cancelled for {nb_path}")
        except Exception as e:
            logger.error(f"Listener error for {nb_path}: {e}")

    async def _stdin_listener(self, nb_path: str, session_data: Dict):
        """
        Background task to handle input() requests from the kernel.
        """
        kc = session_data['kc']
        logger.info(f"Starting stdin listener for {nb_path}")
        
        try:
            while True:
                # Wait for stdin message
                try:
                    # check if stdin_channel is defined and alive
                    if not kc.stdin_channel.is_alive():
                         await asyncio.sleep(0.5)
                         continue
                    
                    # [ASYNC SAFETY] Use safe async polling
                    # AsyncKernelClient methods are coroutines but might not be thread-safe
                    # so we execute them directly in the event loop not an executor
                    if await kc.stdin_channel.msg_ready():
                        msg = await kc.stdin_channel.get_msg(timeout=0)
                    else:
                        await asyncio.sleep(0.1)
                        continue
                        
                except Exception:
                    # Timeout or Empty, just loop
                    await asyncio.sleep(0.1)
                    continue

                msg_type = msg['header']['msg_type']
                content = msg['content']
                
                if msg_type == 'input_request':
                    logger.info(f"Kernel requested input: {content.get('prompt', '')}")
                    
                    # Notify Client to Ask User
                    await self._send_notification("notebook/input_request", {
                        "notebook_path": nb_path,
                        "prompt": content.get('prompt', ''),
                        "password": content.get('password', False)
                    })

                    # [FIX] Start an input watchdog so a disconnected client cannot
                    # block the kernel indefinitely. We set a 'waiting_for_input'
                    # flag in the session and wait for submit_input to clear it.
                    session_data['waiting_for_input'] = True
                    try:
                        timeout = session_data.get('input_request_timeout', self.input_request_timeout)
                        elapsed = 0.0
                        interval = 0.1
                        timed_out = True
                        while elapsed < timeout:
                            await asyncio.sleep(interval)
                            elapsed += interval
                            if not session_data.get('waiting_for_input'):
                                timed_out = False
                                break

                        if timed_out:
                            logger.warning(f"Input request timed out for {nb_path} after {timeout}s. Attempting to recover.")
                            # Try sending an empty input to unblock the kernel
                            try:
                                kc.input('')
                                logger.info("Sent empty string to kernel to clear input request")
                            except Exception as e:
                                logger.warning(f"Failed to send empty input: {e}. Sending interrupt as fallback.")
                                await self.interrupt_kernel(nb_path)
                    finally:
                        session_data['waiting_for_input'] = False
                    
        except asyncio.CancelledError:
            logger.info(f"Stdin listener cancelled for {nb_path}")
        except Exception as e:
            logger.error(f"Stdin listener error for {nb_path}: {e}")
        # If we don't have a kernel client (test mode or transient), just clear the flag
        if kc is None:
            session['waiting_for_input'] = False
            logger.info(f"No kernel client for {notebook_path}; cleared waiting_for_input flag")
            return

        try:
            kc.input(text)
            logger.info(f"Sent input to {notebook_path}")
        finally:
            # Signal to any pending watchdog that input was provided
            session['waiting_for_input'] = False

    async def _queue_processor(self, nb_path: str, session_data: Dict):
        """
        Background loop that processes execution requests from the queue.
        Ensures only one cell executes at a time per notebook.
        """
        logger.info(f"Starting queue processor for {nb_path}")
        try:
            while True:
                # Get next execution request from queue
                exec_request = await session_data['execution_queue'].get()
                
                # Check for shutdown signal
                if exec_request is None:
                    logger.info(f"Queue processor shutting down for {nb_path}")
                    break
                
                cell_index = exec_request['cell_index']
                code = exec_request['code']
                exec_id = exec_request['exec_id']
                
                # Remove from queued executions (now processing)
                if exec_id in session_data['queued_executions']:
                    del session_data['queued_executions'][exec_id]
                
                # [SCIENTIFIC INTEGRITY] Check Linearity
                current_index = cell_index
                max_idx = session_data.get('max_executed_index', -1)
                
                linearity_warning = ""
                if current_index >= 0 and current_index < max_idx:
                    # Agent is executing out of order (e.g., edited Cell 1 after running Cell 3)
                    linearity_warning = (
                        f"\n\n⚠️  [INTEGRITY WARNING] You are executing Cell {current_index + 1} "
                        f"after Cell {max_idx + 1}. This creates hidden state. "
                        f"The notebook state in memory (Cell {current_index + 1} v2 + later cells v1) "
                        f"cannot be reproduced by running 'Run All' from top to bottom. "
                        f"Recommend re-running subsequent cells to ensure reproducibility.\n"
                    )
                
                # Update wavefront (track highest executed index)
                if current_index > max_idx:
                    session_data['max_executed_index'] = current_index
                
                try:
                    # Increment execution counter
                    session_data['execution_counter'] += 1
                    expected_count = session_data['execution_counter']
                    
                    # Execute the cell
                    kc = session_data['kc']
                    msg_id = kc.execute(code)
                    
                    # Register execution with expected count
                    session_data['executions'][msg_id] = {
                        'id': exec_id,
                        'cell_index': cell_index,
                        'status': 'running',
                        'outputs': [],
                        'execution_count': expected_count,
                        'text_summary': linearity_warning,  # [SCIENTIFIC INTEGRITY] Inject warning
                        'kernel_state': 'busy',
                        'start_time': asyncio.get_event_loop().time(),
                        'output_count': 0,  # [PHASE 3.1] Track total output count for streaming
                        'last_activity': asyncio.get_event_loop().time(),  # [PHASE 3.1] Last output timestamp
                        'finalization_event': asyncio.Event(), # [RACE CONDITION FIX]
                    }
                    
                    # Wait for execution to complete with timeout
                    # Use per-session timeout
                    session_timeout = session_data.get('execution_timeout', self.default_execution_timeout)
                    timeout_remaining = session_timeout
                    while timeout_remaining > 0:
                        await asyncio.sleep(0.5)
                        timeout_remaining -= 0.5
                        
                        exec_data = session_data['executions'].get(msg_id)
                        if exec_data and exec_data['status'] in ['completed', 'error', 'cancelled']:
                            # Check if we should stop on error
                            if exec_data['status'] == 'error' and session_data.get('stop_on_error', False):
                                logger.warning(f"Execution failed for cell {cell_index}, clearing remaining queue (stop_on_error=True)")
                                # Clear remaining queue items
                                while not session_data['execution_queue'].empty():
                                    try:
                                        session_data['execution_queue'].get_nowait()
                                    except asyncio.QueueEmpty:
                                        break
                            
                            # [RACE CONDITION FIX] Signal that finalization can proceed.
                            exec_data['finalization_event'].set()
                            break # Exit timeout loop
                    
                    # [RACE CONDITION FIX] Also signal on timeout to prevent deadlocks
                    exec_data = session_data['executions'].get(msg_id)
                    if exec_data:
                        exec_data['finalization_event'].set()

                    if timeout_remaining <= 0:
                        # Handle timeout
                        logger.warning(f"Execution timed out for cell {cell_index} in {nb_path}")
                        if msg_id in session_data['executions']:
                            session_data['executions'][msg_id]['status'] = 'timeout'
                            session_data['executions'][msg_id]['error'] = f"Execution exceeded {session_timeout}s timeout"
                        
                        # If stop_on_error, also stop on timeout
                        if session_data.get('stop_on_error', False):
                            logger.warning(f"Execution timeout, clearing remaining queue (stop_on_error=True)")
                            while not session_data['execution_queue'].empty():
                                try:
                                    cancelled_request = session_data['execution_queue'].get_nowait()
                                    if cancelled_request is not None:
                                        cancelled_id = cancelled_request['exec_id']
                                        for msg_id_cancel, data_cancel in session_data['executions'].items():
                                            if data_cancel.get('id') == cancelled_id:
                                                data_cancel['status'] = 'cancelled'
                                                data_cancel['error'] = f"Cancelled due to timeout in cell {cell_index}"
                                                break
                                        session_data['execution_queue'].task_done()
                                except asyncio.QueueEmpty:
                                    break
                    
                except Exception as e:
                    logger.error(f"Error executing cell {cell_index} in {nb_path}: {e}")
                    # Mark execution as failed
                    if exec_id:
                        for msg_id, data in session_data['executions'].items():
                            if data['id'] == exec_id:
                                data['status'] = 'error'
                                data['error'] = str(e)
                                break
                    
                    # If stop_on_error, clear remaining queue
                    if session_data.get('stop_on_error', False):
                        logger.warning(f"Exception during execution, clearing remaining queue (stop_on_error=True)")
                        while not session_data['execution_queue'].empty():
                            try:
                                cancelled_request = session_data['execution_queue'].get_nowait()
                                if cancelled_request is not None:
                                    session_data['execution_queue'].task_done()
                            except asyncio.QueueEmpty:
                                break
                finally:
                    # Mark task as done
                    session_data['execution_queue'].task_done()
        
        except asyncio.CancelledError:
            logger.info(f"Queue processor cancelled for {nb_path}")
        except Exception as e:
            logger.error(f"Queue processor error for {nb_path}: {e}")

    async def _finalize_execution_async(self, nb_path: str, exec_data: Dict):
        """Async implementation of finalizing an execution. Use `_finalize_execution` wrapper for sync callers."""
        try:
            # 1. Save Assets and get text summary (async-safe)
            assets_dir = str(Path(nb_path).parent / "assets")
            try:
                text_summary = await utils._sanitize_outputs_async(exec_data['outputs'], assets_dir)
            except Exception as e:
                logger.warning(f"sanitize_outputs failed: {e}")
                text_summary = '{"llm_summary": "", "raw_outputs": []}'

            exec_data['text_summary'] = text_summary
            # Debug: log finalizer summary lengths for observability during tests
            try:
                logger.info(f"Finalize exec {exec_data.get('id')} text_summary len: {len(text_summary)}")
            except Exception:
                pass
            
            # 2. Get Cell content for content hashing
            abs_path = str(Path(nb_path).resolve())
            execution_hash = None

            # Some internal/server-side helper executions (e.g. variable manifest refresh)
            # use cell_index = -1 to indicate "not associated with a notebook cell".
            # In that case, skip notebook hashing/metadata injection and never attempt disk writes.
            cell_index = exec_data.get('cell_index', None)
            if cell_index is None or cell_index < 0:
                cell_index = None
            
            try:
                if cell_index is not None:
                    # Load notebook to get Cell info
                    with open(nb_path, 'r', encoding='utf-8') as f:
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
                    env_info = self.sessions[abs_path].get('env_info', {})
                    
                    metadata_update = {
                        "execution_hash": execution_hash,
                        "execution_timestamp": datetime.datetime.now().isoformat(),
                        "kernel_env_name": env_info.get('env_name', 'unknown'),
                        "agent_run_id": str(uuid.uuid4())
                    }
                except Exception as e:
                    logger.warning(f"Failed to prepare metadata: {e}")
            
            # 4. Write to Notebook File WITH metadata injection
            # If there are active WebSocket clients, avoid writing to disk to
            # prevent file watcher conflicts in editors (e.g. VS Code).
            active_clients = 0
            if hasattr(self, 'connection_manager') and self.connection_manager:
                try:
                    active_clients = len(self.connection_manager.active_connections)
                except Exception:
                    active_clients = 0

            if active_clients > 0:
                logger.info(f"Skipping disk write for {nb_path} (clients connected={active_clients}). Updates were broadcasted to clients.")
            else:
                # Only persist outputs back into the notebook when this execution maps to a real cell.
                if cell_index is not None:
                    notebook.save_cell_execution(
                        nb_path,
                        cell_index,
                        exec_data['outputs'],
                        exec_data.get('execution_count'),
                        metadata_update=metadata_update if metadata_update else None
                    )
        except Exception as e:
            exec_data['status'] = 'failed_save'
            exec_data['error'] = str(e)
            logger.error(f"Failed to finalize execution: {e}")

    async def execute_cell_async(self, nb_path: str, cell_index: int, code: str, exec_id: Optional[str] = None) -> Optional[str]:
        """Submits execution to the queue and returns an ID immediately."""
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
        
        session = self.sessions[abs_path]
        
        # Check if there are queued executions waiting to be processed
        if session['queued_executions']:
            return True
        
        # Check if there are active executions currently running
        for msg_id, data in session['executions'].items():
            if data['status'] in ['busy', 'queued']:
                return True
        
        return False

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

    async def save_checkpoint(self, notebook_path: str, checkpoint_name: str):
        """[RECIPE REPLAY] Save the execution history, not the heap."""
        session = self.sessions.get(str(Path(notebook_path).resolve()))
        if not session: return "No session"

        # Get the history of executed cell indices
        executed_indices = sorted(list(session.get('executed_indices', set())))
        if not executed_indices:
            return "No cells have been executed; nothing to save."

        # Read the notebook to get the source of executed cells
        try:
            nb = nbformat.read(notebook_path, as_version=4)
        except Exception as e:
            return f"Error reading notebook: {e}"

        # Create the recipe
        recipe = []
        for index in executed_indices:
            if 0 <= index < len(nb.cells):
                cell = nb.cells[index]
                if cell.cell_type == 'code':
                    recipe.append({
                        "index": index,
                        "source": cell.source
                    })
        
        # Save the recipe to disk
        ckpt_path = Path(notebook_path).parent / ".mcp" / f"{checkpoint_name}.json"
        ckpt_path.parent.mkdir(exist_ok=True, parents=True)
        
        manifest = {
            "version": "2.0",
            "type": "recipe_replay",
            "timestamp": datetime.datetime.now().isoformat(),
            "notebook_path": notebook_path,
            "recipe": recipe
        }
        
        try:
            with open(ckpt_path, 'w') as f:
                json.dump(manifest, f, indent=2)
            return f"Checkpoint recipe saved. Contains {len(recipe)} executed cells."
        except Exception as e:
            return f"Failed to save checkpoint recipe: {e}"

    async def load_checkpoint(self, notebook_path: str, checkpoint_name: str):
        """[RECIPE REPLAY] Restore state by re-executing from a recipe."""
        ckpt_path = Path(notebook_path).parent / ".mcp" / f"{checkpoint_name}.json"
        if not ckpt_path.exists():
            return f"Checkpoint recipe not found: {ckpt_path}"

        try:
            with open(ckpt_path, 'r') as f:
                manifest = json.load(f)
        except Exception as e:
            return f"Failed to read checkpoint recipe: {e}"

        # 1. Restart the kernel for a clean slate
        await self.restart_kernel(notebook_path)
        await asyncio.sleep(2) # Give kernel time to be ready

        # 2. Concatenate all code into a single block for fast replay
        full_code = "\n\n# --- Recipe Replay ---\n\n".join(
            [cell['source'] for cell in manifest.get('recipe', [])]
        )
        
        if not full_code:
            return "Checkpoint recipe is empty; nothing to replay."

        # 3. Execute the combined code block
        # We use a special index -2 to signify a replay operation
        exec_id = await self.execute_cell_async(notebook_path, -2, full_code)
        
        return f"State restoration started by replaying {len(manifest.get('recipe', []))} cells. Task ID: {exec_id}"

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

    async def _run_and_wait_internal(self, nb_path: str, code: str):
        """Internal helper to run code via the async system and wait for result."""
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions: return "Error: No kernel."
        
        # We use cell_index -1 to denote internal/temporary
        exec_id = await self.execute_cell_async(nb_path, -1, code)
        if not exec_id: return "Error starting internal execution."
        
        # Wait loop
        for _ in range(60): # Write max wait 30s (60 * 0.5)
            await asyncio.sleep(0.5)
            status = self.get_execution_status(nb_path, exec_id)
            if status['status'] in ['completed', 'error']:
                return status['output']
        
        return "Error: Timeout waiting for internal command."

    async def run_simple_code(self, nb_path: str, code: str):
         return await self._run_and_wait_internal(nb_path, code)

    async def stop_kernel(self, nb_path: str, cleanup_assets: bool = True):
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions: return "No running kernel."
        
        session = self.sessions[abs_path]
        
        # [FIX #8] Session-scoped asset cleanup (GDPR compliance)
        if cleanup_assets:
            try:
                # Get session start time
                start_time_str = session.get('env_info', {}).get('start_time')
                if start_time_str:
                    import datetime
                    start_time = datetime.datetime.fromisoformat(start_time_str).timestamp()
                    
                    # Clean up assets created during this session only
                    asset_dir = Path(nb_path).parent / "assets"
                    if asset_dir.exists():
                        deleted_count = 0
                        for asset in asset_dir.glob("*"):
                            if asset.is_file() and asset.stat().st_mtime > start_time:
                                try:
                                    asset.unlink()
                                    deleted_count += 1
                                    logger.info(f"[ASSET CLEANUP] Deleted session asset: {asset.name}")
                                except Exception as e:
                                    logger.warning(f"[ASSET CLEANUP] Failed to delete {asset.name}: {e}")
                        
                        if deleted_count > 0:
                            logger.info(f"[ASSET CLEANUP] Removed {deleted_count} session-scoped assets")
                
                # Also run standard garbage collection
                from src.asset_manager import prune_unused_assets
                cleanup_result = prune_unused_assets(abs_path, dry_run=False)
                logger.info(f"[ASSET CLEANUP] Prune result: {cleanup_result.get('message', 'completed')}")
            except Exception as e:
                logger.warning(f"[ASSET CLEANUP] Failed: {e}")
        
        # Signal queue processor to stop
        if session.get('queue_processor_task'):
            await session['execution_queue'].put(None)  # Shutdown signal
            session['queue_processor_task'].cancel()
            try:
                await session['queue_processor_task']
            except asyncio.CancelledError:
                pass
        
        # Cancel Listener
        if session['listener_task']:
            session['listener_task'].cancel()
            try:
                await session['listener_task']
            except asyncio.CancelledError:
                pass

        # Cancel Stdin Listener
        if session.get('stdin_listener_task'):
            session['stdin_listener_task'].cancel()
            try:
                await session['stdin_listener_task']
            except asyncio.CancelledError:
                pass
        
        # [FIX #4] Cancel health check task
        if session.get('health_check_task'):
            session['health_check_task'].cancel()
            try:
                await session['health_check_task']
            except asyncio.CancelledError:
                pass

        session['kc'].stop_channels()
        await session['km'].shutdown_kernel()
        del self.sessions[abs_path]
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
            await session['km'].interrupt_kernel()
            logger.info(f"[CANCEL] Stage 1: Sent SIGINT to {nb_path}")
        except Exception as e:
            logger.error(f"[CANCEL] Failed to send SIGINT: {e}")
            return f"Failed to interrupt: {e}"
        
        # Wait 3 seconds, checking every 0.5s
        for i in range(6):
            await asyncio.sleep(0.5)
            
            # Check if execution completed/cancelled
            if exec_id and exec_id in session['executions']:
                status = session['executions'][exec_id].get('status')
                if status in ['cancelled', 'error', 'completed']:
                    logger.info(f"[CANCEL] Stage 1 succeeded (SIGINT)")
                    return "Cancelled gracefully (SIGINT)"
            
            # Check kernel client responsiveness
            kc = session.get('kc')
            if kc and not kc.is_alive():
                logger.warning(f"[CANCEL] Kernel died during interrupt")
                return "Kernel terminated"
        
        # Stage 2: SIGINT failed, escalate to SIGTERM
        logger.warning(f"[CANCEL] Stage 1 failed, escalating to Stage 2: SIGTERM")
        try:
            km = session['km']
            if hasattr(km, 'kernel') and km.kernel:
                import signal
                km.kernel.send_signal(signal.SIGTERM)
                logger.info(f"[CANCEL] Stage 2: Sent SIGTERM to PID {km.kernel.pid}")
        except Exception as e:
            logger.error(f"[CANCEL] Failed to send SIGTERM: {e}")
        
        # Wait 2 seconds
        await asyncio.sleep(2)
        
        # Check if kernel stopped
        kc = session.get('kc')
        if kc and not kc.is_alive():
            logger.info(f"[CANCEL] Stage 2 succeeded (SIGTERM)")
            return "Force terminated (SIGTERM)"
        
        # Stage 3: Nuclear option - SIGKILL + restart
        logger.error(f"[CANCEL] Stage 2 failed, escalating to Stage 3: SIGKILL + restart")
        try:
            km = session['km']
            if hasattr(km, 'kernel') and km.kernel:
                import signal
                km.kernel.send_signal(signal.SIGKILL)
                logger.info(f"[CANCEL] Stage 3: Sent SIGKILL to PID {km.kernel.pid}")
                
            # Force cleanup
            await self.stop_kernel(nb_path, cleanup_assets=False)
            
            # Attempt restart with state recovery
            logger.info(f"[CANCEL] Attempting kernel restart...")
            await self.start_kernel(nb_path)
            
            # Try to restore from checkpoint if available
            checkpoint_dir = Path(nb_path).parent / ".mcp"
            if checkpoint_dir.exists():
                checkpoints = list(checkpoint_dir.glob("*.json"))
                if checkpoints:
                    latest = max(checkpoints, key=lambda p: p.stat().st_mtime)
                    logger.info(f"[CANCEL] Restoring from checkpoint: {latest.name}")
                    # Note: load_checkpoint is async, but we don't await to avoid blocking
                    asyncio.create_task(self.load_checkpoint(nb_path, latest.stem))
                    return "Killed and restarted (state restored from checkpoint)"
            
            return "Killed and restarted (state lost - no checkpoint available)"
            
        except Exception as e:
            logger.error(f"[CANCEL] Stage 3 failed: {e}")
            return f"Failed to kill and restart: {e}"

        # We manually mark the specific execution as cancelled if found (Force fallback)
        if exec_id is not None:
             for msg_id, data in session['executions'].items():
                if data['id'] == exec_id and data['status'] == 'running':
                    data['status'] = 'cancelled'
                    return "Kernel interrupted successfully (Marked as cancelled)."

        return "Warning: Kernel sent interrupt signal but is still busy. It may be catching KeyboardInterrupt."

    async def shutdown_all(self):
        """Kills all running kernels and cleans up persisted session files."""
        for abs_path, session in list(self.sessions.items()):
            if session.get('listener_task'):
                session['listener_task'].cancel()
            try:
                await session['km'].shutdown_kernel(now=True)
                # Remove persisted session info
                self._remove_persisted_session(abs_path)
            except Exception as e:
                logging.error(f"Error shutting down kernel for {abs_path}: {e}")
        self.sessions.clear()

    # --- Preserved Helper Methods ---

    async def install_package(self, nb_path: str, package_name: str):
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
             return "Error: No running kernel to install into."
        
        session = self.sessions[abs_path]
        km = session['km']
        cmd = km.kernel_cmd
        if not cmd:
             return "Error: Could not determine kernel python path."
        
        python_executable = cmd[0]
        
        # Run pip install
        proc = await asyncio.create_subprocess_exec(
            python_executable, "-m", "pip", "install", package_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
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
         pass # Using main.py's implementation which calls run_simple_code

    async def interrupt_kernel(self, nb_path: str):
        return await self.cancel_execution(nb_path, None)

    async def restart_kernel(self, nb_path: str):
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
             return "Error: No running kernel."

        # [ASSET CLEANUP] Run GC before restart to clean up orphaned assets.
        # This ensures "Clear Output + Save" or manual edits don't leave assets behind across restarts.
        try:
            from src.asset_manager import prune_unused_assets
            cleanup_result = prune_unused_assets(abs_path, dry_run=False)
            logger.info(f"Asset cleanup on kernel restart: {cleanup_result.get('message', 'completed')}")
        except Exception as e:
            logger.warning(f"Asset cleanup on restart failed: {e}")

        session = self.sessions[abs_path]
        await session['km'].restart_kernel()
        # Note: Restarting might break the listener connection? 
        # Typically jupyter_client handles this, but if channels die we might need to recreate them.
        # For now, assume it recovers or user must restart kernel via stop/start if it breaks.
        return "Kernel restarted."
    
    def list_environments(self):
        """Scans for potential Python environments."""
        envs = []
        
        # 1. Current System Python
        envs.append({"name": "System/Global", "path": sys.executable})
        
        # 2. Check common locations relative to user home
        home = Path.home()
        candidates = [
            home / ".virtualenvs",
            home / "miniconda3" / "envs",
            home / "anaconda3" / "envs",
            Path("."), # Current folder
            Path(".venv"), 
            Path("venv"),
            Path("env")
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
                                envs.append({"name": f"Found: {sub.name}", "path": str(sub)})

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
            km = self.sessions[abs_path]['km']
            
            # Safely get PID (same pattern as start_kernel)
            if not hasattr(km, 'kernel') or not km.kernel:
                return {"error": "Kernel process not found"}
            
            pid = getattr(km.kernel, 'pid', None)
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
                "num_children": len(children)
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
        
        [REAPER FIX] Only kills kernels whose owning server is dead.
        This prevents fratricide: Server B won't kill Kernel A if Server A is still alive.
        
        Scenario that was broken:
        1. User opens VS Code Window A → Server A starts, Kernel A (PID 1000)
        2. User opens VS Code Window B → Server B starts
        3. Server B runs reconcile_zombies, sees Kernel A (PID 1000)
        4. OLD BUG: Server B kills Kernel A (fratricide)
        5. NEW FIX: Server B checks if Server A is alive first
        """
        try:
            import psutil
            import json
        except Exception:
            logger.warning("reaper_skipped_no_psutil")
            return

        logger.info("reaper_start: Scanning for zombie kernels...")
        current_server_pid = os.getpid()

        for session_file in list(self.persistence_dir.glob("session_*.json")):
            try:
                with open(session_file, 'r') as f:
                    data = json.load(f)

                kernel_pid = data.get('pid')
                server_pid = data.get('server_pid')  # [REAPER FIX] Check server ownership
                
                # Skip if this session belongs to us (we'll manage it ourselves)
                if server_pid == current_server_pid:
                    continue
                
                # Check if the owning server is still alive
                if server_pid and psutil.pid_exists(server_pid):
                    # Server is alive → this is NOT a zombie, it's a living kernel from another window
                    logger.debug(f"reaper_skip: Kernel PID {kernel_pid} belongs to living server PID {server_pid}")
                    continue
                
                # Server is dead → this kernel is an orphan, kill it
                if kernel_pid and psutil.pid_exists(kernel_pid):
                    try:
                        proc = psutil.Process(kernel_pid)
                        cmdline = " ".join(proc.cmdline())
                        # Heuristic checks: ipykernel / jupyter / python
                        if any(x in cmdline for x in ('ipykernel', 'ipython', 'jupyter', 'python')):
                            logger.warning(f"reaper_kill: Kernel PID {kernel_pid} (dead server PID {server_pid}) notebook={data.get('notebook_path')}")
                            proc.terminate()
                            try:
                                proc.wait(timeout=2)
                            except psutil.TimeoutExpired:
                                proc.kill()
                    except Exception as e:
                        logger.warning(f"reaper_proc_check_failed pid={kernel_pid} error={str(e)}")

                # Remove persisted session file (best-effort cleanup)
                try:
                    session_file.unlink()
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"reaper_error file={str(session_file)} error={str(e)}")
                try:
                    session_file.unlink()
                except Exception:
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
        loop = asyncio.get_running_loop()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(asyncio.run, self._finalize_execution_async(nb_path, exec_data))
            return fut.result()
    except RuntimeError:
        # No running loop — run synchronously
        return asyncio.run(self._finalize_execution_async(nb_path, exec_data))

# Attach wrapper to class
SessionManager._finalize_execution = _finalize_execution
