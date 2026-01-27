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
        self._persistence_available = False
        try:
            self.persistence_dir.mkdir(parents=True, exist_ok=True)
            self._persistence_available = True
        except (PermissionError, OSError) as e:
            logger.critical(
                f"CRITICAL: Failed to create persistence directory {persistence_dir}: {e}. "
                "Zombie kernel reaping is DISABLED. Server will leak kernel processes."
            )
            # Fail fast: In production, this should crash the server
            # Set MCP_FAIL_FAST_ON_PERSISTENCE=1 to enforce
            if os.getenv("MCP_FAIL_FAST_ON_PERSISTENCE") == "1":
                raise RuntimeError(
                    f"Cannot start server: Persistence directory {persistence_dir} is not writable. "
                    "This will cause kernel process leaks."
                ) from e
        self._session_locks = {}

    def persist_session(
        self,
        nb_path: str,
        connection_file: str,
        pid: Any,
        env_info: Dict,
        kernel_uuid: Optional[str] = None,
        executed_indices: Optional[set] = None,
    ):
        """Save session info to disk to prevent zombie kernels after server restart."""
        # Alert if persistence directory is not available
        if not self._persistence_available:
            logger.error(
                f"[OPERATIONAL RISK] Cannot persist session for {nb_path}: "
                "Persistence layer is disabled. Kernel PID {pid} will become a zombie if server crashes."
            )
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
                "created_at": datetime.datetime.now().isoformat(),
                # [SMART SYNC FIX] Persist executed cell indices for session restore
                "executed_indices": list(executed_indices) if executed_indices else [],
            }

            with open(session_file, "w") as f:
                json.dump(session_data, f, indent=2)

            # [COMPLIANCE] Set file permissions to 600 (owner read/write only)
            os.chmod(session_file, 0o600)

            # Create and hold a lock file
            lock_file = self.persistence_dir / f"session_{path_hash}.lock"
            self._acquire_lock(lock_file, nb_path)

            logger.info(f"Persisted session info for {nb_path} (PID: {pid})")
        except Exception as e:
            logger.warning(f"Failed to persist session info: {e}")

    def _acquire_lock(self, lock_file: Path, nb_path: str):
        """Platform-independent file locking using `filelock` with robust fallbacks."""
        try:
            # Preferred: filelock (cross-platform, atomic semantics)
            from filelock import FileLock, Timeout

            fl = FileLock(str(lock_file))
            try:
                fl.acquire(timeout=0)
                self._session_locks[nb_path] = fl
            except Timeout:
                logger.warning(f"Lock already held for {nb_path}")
                return
        except ImportError:
            # Fallback to fcntl on Unix-like systems
            try:
                import fcntl

                lock_fd = open(lock_file, "w")
                fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._session_locks[nb_path] = lock_fd
                return
            except Exception:
                pass

            # Fallback to portalocker on Windows
            try:
                import portalocker

                lock_fd = open(lock_file, "w")
                portalocker.lock(lock_fd, portalocker.LOCK_EX | portalocker.LOCK_NB)
                self._session_locks[nb_path] = lock_fd
                return
            except Exception:
                pass

            # Last-resort: atomic create via O_EXCL
            try:
                fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    f.write(str(os.getpid()))
                logger.warning(f"Using atomic-create lock for {nb_path}")
            except FileExistsError:
                logger.warning(f"Lock already exists for {nb_path}")
            except Exception as e:
                logger.warning(f"Using weak locking for {nb_path}: {e}")

    def remove_session(self, nb_path: str):
        """Remove persisted session info and locks."""
        # Skip if persistence directory is not available
        if not self.persistence_dir.exists():
            logger.debug(
                f"Skipping session removal for {nb_path}: directory unavailable"
            )
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
                lock = self._session_locks[nb_path]
                try:
                    if hasattr(lock, "release"):
                        lock.release()
                    if hasattr(lock, "close"):
                        lock.close()
                except Exception:
                    pass
                finally:
                    del self._session_locks[nb_path]

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
        # Alert critically if persistence directory is not available
        if not self._persistence_available:
            logger.critical(
                "[REAPER DISABLED] Zombie kernel reconciliation is DISABLED due to persistence failure. "
                "Orphaned kernel processes will accumulate and exhaust system resources."
            )
            return

        logger.info("reaper_start: Scanning for zombie kernels...")
        current_server_pid = os.getpid()

        for session_file in list(self.persistence_dir.glob("session_*.json")):
            try:
                with open(session_file, "r") as f:
                    data = json.load(f)

                server_pid = data.get("server_pid")
                kernel_pid = data.get("pid")
                data.get("pid_create_time")
                kernel_uuid = data.get("kernel_uuid")

                # Skip our own sessions
                if server_pid == current_server_pid:
                    continue

                # Check if owning server is alive
                if server_pid and psutil.pid_exists(server_pid):
                    continue  # Server is alive, leave it alone

                # Server is dead -> Check kernel

                # [REAPER FIX] Explicit container cleanup
                env_info = data.get("env_info", {})
                container_name = env_info.get("container_name")
                if container_name:
                    try:
                        import subprocess

                        logger.warning(
                            f"[REAPER] Killing zombie container {container_name}"
                        )
                        subprocess.run(
                            ["docker", "rm", "-f", container_name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5,
                        )
                    except Exception as e:
                        logger.error(f"[REAPER] Docker cleanup failed: {e}")

                if kernel_pid and psutil.pid_exists(kernel_pid):
                    try:
                        proc = psutil.Process(kernel_pid)
                        should_kill = False

                        # [P0 FIX #4] UUID Check is MANDATORY - no fallback to create_time
                        if kernel_uuid:
                            try:
                                # Try psutil first, but fallback to reading /proc/<pid>/environ
                                try:
                                    proc_env = proc.environ()
                                except Exception:
                                    proc_env = {}
                                if not proc_env:
                                    try:
                                        with open(f"/proc/{kernel_pid}/environ", "rb") as f:
                                            raw = f.read().decode(errors="ignore")
                                            parts = raw.split("\x00")
                                            proc_env = {p.split("=",1)[0]: p.split("=",1)[1] for p in parts if "=" in p}
                                    except Exception:
                                        proc_env = {}

                                if proc_env.get("MCP_KERNEL_ID") == kernel_uuid:
                                    should_kill = True
                                    logger.info(
                                        f"[REAPER] UUID match confirmed for PID {kernel_pid} "
                                        f"(UUID: {kernel_uuid[:8]}...)"
                                    )
                                else:
                                    # As a fallback, check recorded pid_create_time. If the process
                                    # creation time matches the persisted pid_create_time, it's
                                    # very likely the same process and safe to kill even when the
                                    # environment variable wasn't found (some platforms restrict access).
                                    recorded_create_time = data.get("pid_create_time")
                                    try:
                                        proc_create_time = proc.create_time()
                                    except Exception:
                                        proc_create_time = None

                                    if (
                                        recorded_create_time
                                        and proc_create_time
                                        and abs(proc_create_time - recorded_create_time) < 1.0
                                    ):
                                        should_kill = True
                                        logger.warning(
                                            f"[REAPER] PID {kernel_pid} env UUID not readable, but create_time matches persisted record. Reaping PID."
                                        )
                                    else:
                                        logger.warning(
                                            f"[REAPER] PID {kernel_pid} exists but UUID mismatch. "
                                            f"Expected {kernel_uuid[:8]}..., got {proc_env.get('MCP_KERNEL_ID', 'NONE')[:8] if proc_env.get('MCP_KERNEL_ID') else 'NONE'}... "
                                            "Skipping (possible PID recycling)."
                                        )
                            except (psutil.AccessDenied, psutil.NoSuchProcess) as e:
                                logger.error(
                                    f"[REAPER] Cannot verify UUID for PID {kernel_pid}: {e}. "
                                    "Refusing to kill process without UUID verification (PID recycling risk)."
                                )
                        else:
                            logger.warning(
                                f"[REAPER] Session {session_file.name} has no kernel_uuid. "
                                "Legacy sessions without UUID cannot be safely reaped (PID recycling risk). "
                                "Skipping."
                            )

                        if should_kill:
                            logger.warning(
                                f"[REAPER] Killing zombie kernel {kernel_pid}"
                            )
                            proc.terminate()
                            try:
                                proc.wait(timeout=2)
                            except psutil.TimeoutExpired:
                                proc.kill()
                    except Exception as e:
                        logger.warning(
                            f"[REAPER] Error handling process {kernel_pid}: {e}"
                        )

                # Cleanup file
                try:
                    session_file.unlink()
                    lock_file = session_file.with_suffix(".lock")
                    if lock_file.exists():
                        lock_file.unlink()
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"[REAPER] File error: {e}")
