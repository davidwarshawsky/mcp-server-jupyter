import os
import json
import psutil
import logging
import datetime
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class KernelStateManager:
    """
    Handles the persistence of session information, file locking to prevent 
    race conditions, and the 'Grim Reaper' logic to kill zombie kernels.
    """
    def __init__(self, persistence_dir: Path):
        self.persistence_dir = persistence_dir
        try:
            self.persistence_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            logger.error(f"Failed to create persistence directory {persistence_dir}: {e}")
            logger.warning("Session persistence disabled due to directory creation failure")
        self._session_locks = {}

    def persist_session(self, nb_path: str, connection_file: str, pid: Any, env_info: Dict, kernel_uuid: Optional[str] = None):
        """Save session info to disk to prevent zombie kernels after server restart."""
        # Skip if persistence directory is not available
        if not self.persistence_dir.exists():
            logger.debug(f"Skipping session persistence for {nb_path}: directory unavailable")
            return
            
        try:
            import hashlib
            path_hash = hashlib.md5(nb_path.encode()).hexdigest()
            session_file = self.persistence_dir / f"session_{path_hash}.json"
            
            current_proc = psutil.Process(os.getpid())
            
            # Track kernel process creation time
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
                "pid_create_time": kernel_create_time,
                "kernel_uuid": kernel_uuid,
                "server_pid": os.getpid(),
                "server_create_time": current_proc.create_time(),
                "env_info": env_info,
                "created_at": datetime.datetime.now().isoformat()
            }
            
            with open(session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            
            # Create and hold a lock file
            lock_file = self.persistence_dir / f"session_{path_hash}.lock"
            self._acquire_lock(lock_file, nb_path)
            
            logger.info(f"Persisted session info for {nb_path} (PID: {pid})")
        except Exception as e:
            logger.warning(f"Failed to persist session info: {e}")

    def _acquire_lock(self, lock_file: Path, nb_path: str):
        """Platform-independent file locking."""
        try:
            # Try fcntl (Unix)
            import fcntl
            lock_fd = open(lock_file, 'w')
            fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._session_locks[nb_path] = lock_fd
        except ImportError:
            # Try portalocker (Windows) or fallback
            try:
                import portalocker
                lock_fd = open(lock_file, 'w')
                portalocker.lock(lock_fd, portalocker.LOCK_EX | portalocker.LOCK_NB)
                self._session_locks[nb_path] = lock_fd
            except (ImportError, Exception):
                # Fallback: simple PID write
                with open(lock_file, 'w') as f:
                    f.write(str(os.getpid()))
                logger.warning(f"Using weak locking for {nb_path}")

    def remove_session(self, nb_path: str):
        """Remove persisted session info and locks."""
        # Skip if persistence directory is not available
        if not self.persistence_dir.exists():
            logger.debug(f"Skipping session removal for {nb_path}: directory unavailable")
            return
            
        try:
            import hashlib
            path_hash = hashlib.md5(nb_path.encode()).hexdigest()
            session_file = self.persistence_dir / f"session_{path_hash}.json"
            lock_file = self.persistence_dir / f"session_{path_hash}.lock"
            
            if session_file.exists():
                session_file.unlink()
            
            # Close and remove lock
            if nb_path in self._session_locks:
                try:
                    self._session_locks[nb_path].close()
                    del self._session_locks[nb_path]
                except Exception:
                    pass
            
            if lock_file.exists():
                lock_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to remove persisted session: {e}")

    def get_persisted_sessions(self):
        """Yields all session JSON objects found in persistence dir."""
        # Return empty list if persistence directory is not available
        if not self.persistence_dir.exists():
            logger.debug("No persisted sessions available: directory does not exist")
            return []
        return self.persistence_dir.glob("session_*.json")

    def reconcile_zombies(self):
        """
        [REAPER] Kills orphan kernels from dead server processes.
        Uses UUID verification and Server PID liveness checks.
        """
        # Skip if persistence directory is not available
        if not self.persistence_dir.exists():
            logger.debug("Skipping zombie reconciliation: persistence directory unavailable")
            return
            
        logger.info("reaper_start: Scanning for zombie kernels...")
        current_server_pid = os.getpid()

        for session_file in list(self.persistence_dir.glob("session_*.json")):
            try:
                with open(session_file, 'r') as f:
                    data = json.load(f)

                server_pid = data.get('server_pid')
                kernel_pid = data.get('pid')
                saved_create_time = data.get('pid_create_time')
                kernel_uuid = data.get('kernel_uuid')
                
                # Skip our own sessions
                if server_pid == current_server_pid:
                    continue
                
                # Check if owning server is alive
                if server_pid and psutil.pid_exists(server_pid):
                    continue # Server is alive, leave it alone
                
                # Server is dead -> Check kernel
                if kernel_pid and psutil.pid_exists(kernel_pid):
                    try:
                        proc = psutil.Process(kernel_pid)
                        should_kill = False
                        
                        # UUID Check (Primary)
                        if kernel_uuid:
                            try:
                                proc_env = proc.environ()
                                if proc_env.get('MCP_KERNEL_ID') == kernel_uuid:
                                    should_kill = True
                            except (psutil.AccessDenied, psutil.NoSuchProcess):
                                # Fallback to create_time
                                if saved_create_time and proc.create_time() == saved_create_time:
                                    should_kill = True
                        # Legacy Check
                        elif saved_create_time and proc.create_time() == saved_create_time:
                             should_kill = True
                        
                        if should_kill:
                            logger.warning(f"[REAPER] Killing zombie kernel {kernel_pid}")
                            proc.terminate()
                            try:
                                proc.wait(timeout=2)
                            except psutil.TimeoutExpired:
                                proc.kill()
                    except Exception as e:
                        logger.warning(f"[REAPER] Error handling process {kernel_pid}: {e}")

                # Cleanup file
                try:
                    session_file.unlink()
                    lock_file = session_file.with_suffix('.lock')
                    if lock_file.exists():
                        lock_file.unlink()
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"[REAPER] File error: {e}")
