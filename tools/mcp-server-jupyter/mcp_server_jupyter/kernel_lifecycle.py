"""
Kernel Lifecycle Management
============================

This module handles local Jupyter kernel process management:
- Starting kernels (local Python, venv, conda)
- Stopping kernels gracefully
- Restarting kernels
- Health monitoring
- Environment detection

Design Goals:
1. Simple, focused responsibility
2. No I/O multiplexing logic (that's IOMultiplexer's job)
3. No execution scheduling (that's ExecutionScheduler's job)
4. Testable in isolation
5. Local-only execution (no containerization or orchestration)
"""

import os
import sys
import uuid
import asyncio
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from jupyter_client.manager import AsyncKernelManager
import structlog
import shutil
import subprocess

from . import utils

logger = structlog.get_logger(__name__)


class KernelLifecycle:
    """
    Manages the lifecycle of Jupyter kernel processes.

    Responsibilities:
    - Start kernels with proper environment configuration
    - Stop kernels gracefully
    - Restart kernels
    - Health monitoring and reaping
    """

    def __init__(self, max_concurrent: int = 10):
        """
        Initialize kernel lifecycle manager.

        Args:
            max_concurrent: Maximum number of concurrent kernels
        """
        self.max_concurrent = max_concurrent
        self.active_kernels: Dict[str, Dict[str, Any]] = {}
        logger.info(f"KernelLifecycle initialized (max_concurrent={max_concurrent})")

    async def _monitor_kernel_process(self, kernel_id: str, km: AsyncKernelManager):
        """
        Monitor the underlying kernel process for unexpected exits and capture exit codes.
        Attempts multiple strategies to locate the subprocess object and will set
        a descriptive error in self.active_kernels if the kernel was OOM-killed.
        """
        try:
            # Give kernel some time to settle
            await asyncio.sleep(1)

            proc = None
            # Try common internal attributes used by different KernelManager implementations
            for attr in ("proc", "_proc", "subprocess", "process"):
                proc = getattr(km, attr, None)
                if proc:
                    break

            exit_code = None
            if proc:
                # Wait for process to exit in executor to avoid blocking event loop
                try:
                    await asyncio.get_event_loop().run_in_executor(None, proc.wait)
                except Exception:
                    pass
                exit_code = getattr(proc, "returncode", None)
            else:
                # Fallback: poll client liveness until it becomes not alive, no exit code available
                try:
                    kc = km.client()
                    while True:
                        try:
                            is_alive = kc.is_alive()
                            # Handle async implementations that return a coroutine
                            if hasattr(is_alive, "__await__") or hasattr(is_alive, "__iter__"):
                                is_alive = await is_alive
                        except Exception:
                            # If liveness check fails, treat as not alive
                            is_alive = False

                        if not is_alive:
                            exit_code = None
                            break
                        await asyncio.sleep(0.5)
                except Exception:
                    # Unable to determine liveness; give up silently
                    return

            # Interpret common OOM signals (137 or -9)
            if exit_code in (137, -9):
                logger.error(
                    f"[Kernel {kernel_id}] CRASH: Out of Memory (Exit Code {exit_code})"
                )
                if kernel_id in self.active_kernels:
                    self.active_kernels[kernel_id]["error"] = (
                        "Kernel crashed due to Out of Memory (OOM). "
                        "Try using DuckDB for large datasets or requesting more RAM."
                    )
            elif exit_code is not None and exit_code != 0:
                logger.error(f"[Kernel {kernel_id}] CRASH: Exit Code {exit_code}")
                if kernel_id in self.active_kernels:
                    self.active_kernels[kernel_id][
                        "error"
                    ] = f"Kernel crashed: Exit Code {exit_code}"
        except Exception as e:
            logger.debug(f"Kernel monitor failed for {kernel_id}: {e}")


    def _configure_local_kernel(
        self, venv_path: Optional[str] = None
    ) -> tuple[Optional[str], str, Dict[str, str]]:
        """
        Configure kernel to run in local Python environment.

        Returns:
            (python_exe, env_name, kernel_env)
        """
        py_exe = sys.executable
        env_name = "system"
        kernel_env = os.environ.copy()

        # [FINAL PUNCH LIST #1] Inject unique UUID for 100% reliable reaping
        kernel_uuid = str(uuid.uuid4())
        kernel_env["MCP_KERNEL_ID"] = kernel_uuid
        logger.info(f"[KERNEL] Assigning UUID: {kernel_uuid}")

        # [PHASE 2] Enforce lockfile for reproducibility
        if Path(".mcp-requirements.lock").exists():
            logger.info("[PHASE 2] Found lockfile, enforcing exact environment")
            kernel_env["MCP_USE_LOCKFILE"] = "1"

        if venv_path:
            venv = Path(venv_path)
            if venv.exists():
                # Try bin/python (Unix) or Scripts/python.exe (Windows)
                py_exe_candidates = [
                    venv / "bin" / "python",
                    venv / "Scripts" / "python.exe",
                ]
                for candidate in py_exe_candidates:
                    if candidate.exists():
                        py_exe = str(candidate)
                        env_name = f"venv:{venv.name}"
                        logger.info(f"Using virtual environment: {venv_path}")
                        break
                else:
                    logger.warning(
                        f"Virtual environment not found at {venv_path}, using system Python"
                    )
            else:
                logger.warning(f"Virtual environment path does not exist: {venv_path}")

        return py_exe, env_name, kernel_env

    async def start_kernel(
        self,
        kernel_id: str,
        notebook_dir: Path,
        venv_path: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> AsyncKernelManager:
        """
        Start a new Jupyter kernel (local Python, venv, or conda).
        Kernels run directly on the host system without containerization.

        Args:
            kernel_id: Unique identifier for this kernel
            notebook_dir: Working directory for the kernel
            venv_path: Optional path to Python environment
            agent_id: Optional agent ID for workspace isolation

        Returns:
            Configured AsyncKernelManager instance

        Raises:
            RuntimeError: If max concurrent kernels exceeded
            ValueError: If configuration is invalid
        """
        # Check kernel limit
        if len(self.active_kernels) >= self.max_concurrent:
            raise RuntimeError(
                f"Maximum concurrent kernels ({self.max_concurrent}) reached. "
                f"Stop an existing kernel first."
            )

        # Handle agent workspace isolation
        if agent_id:
            safe_agent = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(agent_id))
            agent_dir = notebook_dir / f"agent_{safe_agent}"
            agent_dir.mkdir(parents=True, exist_ok=True)
            notebook_dir = agent_dir
            logger.info(f"Agent CWD isolation: agent '{agent_id}' -> {notebook_dir}")

        km = AsyncKernelManager()

        # Local mode only - configure environment
        py_exe, env_name, kernel_env = self._configure_local_kernel(venv_path)
        km.extra_env = kernel_env

        # Start the kernel
        try:
            await km.start_kernel(cwd=str(notebook_dir))
        except Exception as e:
            # [DAY 2 OPT 2.3] ZMQ port conflict detection and user-friendly error
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ["zmq", "bind", "address already in use", "cannot assign requested address"]):
                raise RuntimeError(
                    f"Kernel startup failed due to port conflict. "
                    f"This usually means another Jupyter instance is running or ports 5000-6000 are blocked. "
                    f"Try:\n"
                    f"  1. Kill other Jupyter processes: killall jupyter-kernel\n"
                    f"  2. Check netstat: netstat -an | grep LISTEN\n"
                    f"  3. Wait 30s for ports to release\n"
                    f"Details: {e}"
                ) from e
            raise e

        # [WINDOWS PERMISSIONS FIX] Secure connection file on Windows
        if sys.platform == "win32":
            try:
                import win32api
                import win32security
                import ntsecuritycon as con

                conn_file = km.connection_file
                user, _, _ = win32security.LookupAccountName("", win32api.GetUserName())

                sd = win32security.GetFileSecurity(
                    conn_file, win32security.DACL_SECURITY_INFORMATION
                )
                dacl = win32security.ACL()
                dacl.AddAccessAllowedAce(
                    win32security.ACL_REVISION,
                    con.FILE_GENERIC_READ | con.FILE_GENERIC_WRITE,
                    user,
                )

                sd.SetSecurityDescriptorDacl(1, dacl, 0)
                win32security.SetFileSecurity(
                    conn_file, win32security.DACL_SECURITY_INFORMATION, sd
                )
                logger.info(f"Secured connection file for Windows: {conn_file}")
            except ImportError:
                logger.warning(
                    "pywin32 not installed. Cannot set specific file permissions on Windows for connection file."
                )
            except Exception as e:
                logger.error(
                    f"Failed to set Windows file permissions for connection file: {e}"
                )

        # Track kernel metadata
        self.active_kernels[kernel_id] = {
            "km": km,
            "notebook_dir": str(notebook_dir),
            "python_exe": py_exe,
            "env_name": env_name,
            "started_at": asyncio.get_event_loop().time(),
        }

        logger.info(
            f"[KERNEL] Started {kernel_id}",
            env=env_name,
            cwd=str(notebook_dir),
        )
        # Start background monitor to capture unexpected exits (OOM detection, etc.)
        try:
            asyncio.create_task(self._monitor_kernel_process(kernel_id, km))
        except Exception:
            logger.debug(
                "Failed to start kernel monitor task; continuing without exit-code monitoring"
            )

        return km

    async def stop_kernel(self, kernel_id: str) -> bool:
        """
        Stop a running kernel gracefully.

        Args:
            kernel_id: Kernel to stop

        Returns:
            True if stopped successfully, False if not found
        """
        if kernel_id not in self.active_kernels:
            logger.warning(f"[KERNEL] Cannot stop {kernel_id}: not found")
            return False

        # Debugging aid: log call stack so we can trace who is requesting kernel shutdown
        try:
            import traceback

            stack = "\n".join(traceback.format_stack(limit=10))
            logger.info(f"stop_kernel called for {kernel_id}; call stack:\n{stack}")
        except Exception:
            pass

        kernel_info = self.active_kernels[kernel_id]
        km = kernel_info["km"]

        try:
            await km.shutdown_kernel()
            logger.info(f"[KERNEL] Stopped {kernel_id}")
        except Exception as e:
            logger.error(f"[KERNEL] Error stopping {kernel_id}: {e}")
        finally:
            # Remove internal state
            if kernel_id in self.active_kernels:
                del self.active_kernels[kernel_id]

        return True

    async def restart_kernel(self, kernel_id: str) -> bool:
        """
        Restart a kernel (preserves outputs but clears memory).

        Args:
            kernel_id: Kernel to restart

        Returns:
            True if restarted successfully
        """
        if kernel_id not in self.active_kernels:
            logger.warning(f"[KERNEL] Cannot restart {kernel_id}: not found")
            return False

        kernel_info = self.active_kernels[kernel_id]
        km = kernel_info["km"]

        try:
            await km.restart_kernel()
            logger.info(f"[KERNEL] Restarted {kernel_id}")
            return True
        except Exception as e:
            logger.error(f"[KERNEL] Error restarting {kernel_id}: {e}")
            return False

    async def interrupt_kernel(self, kernel_id: str) -> bool:
        """
        Send interrupt signal (SIGINT/KeyboardInterrupt) to kernel.

        Args:
            kernel_id: Kernel to interrupt

        Returns:
            True if interrupted successfully
        """
        if kernel_id not in self.active_kernels:
            return False

        kernel_info = self.active_kernels[kernel_id]
        km = kernel_info["km"]

        try:
            await km.interrupt_kernel()
            logger.info(f"[KERNEL] Interrupted {kernel_id}")
            return True
        except Exception as e:
            logger.error(f"[KERNEL] Error interrupting {kernel_id}: {e}")
            return False

    def get_kernel_info(self, kernel_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata about a running kernel."""
        return self.active_kernels.get(kernel_id)

    def list_active_kernels(self) -> List[str]:
        """Get list of all active kernel IDs."""
        return list(self.active_kernels.keys())

    async def health_check(self, kernel_id: str) -> Dict[str, Any]:
        """
        Check if kernel is responsive.

        Returns:
            Dict with 'alive' (bool) and 'latency_ms' (float)
        """
        if kernel_id not in self.active_kernels:
            return {"alive": False, "error": "Kernel not found"}

        kernel_info = self.active_kernels[kernel_id]
        km = kernel_info["km"]
        kc = km.client()

        # kc.is_alive may be sync or async depending on client implementation
        try:
            is_alive = kc.is_alive()
            if hasattr(is_alive, "__await__") or hasattr(is_alive, "__iter__"):
                is_alive = await is_alive
        except Exception:
            is_alive = False

        if not is_alive:
            return {"alive": False, "error": "Client not alive"}

        # Try kernel_info request with timeout
        import time

        start = time.time()
        try:
            await asyncio.wait_for(kc.kernel_info(), timeout=5.0)
            latency = (time.time() - start) * 1000
            return {"alive": True, "latency_ms": round(latency, 2)}
        except asyncio.TimeoutError:
            return {"alive": False, "error": "Timeout waiting for kernel_info"}
        except Exception as e:
            return {"alive": False, "error": str(e)}
