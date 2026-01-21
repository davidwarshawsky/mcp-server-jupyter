"""
Kernel Lifecycle Management
============================

Phase 2.1 Refactoring: Extract kernel process management from SessionManager.

This module handles:
- Starting kernels (local Python, venv, conda, Docker)
- Stopping kernels gracefully
- Restarting kernels
- Health monitoring
- Environment detection
- Resource limit enforcement

Design Goals:
1. < 300 lines (focused responsibility)
2. No I/O multiplexing logic (that's IOMultiplexer's job)
3. No execution scheduling (that's ExecutionScheduler's job)
4. Testable in isolation
"""

import os
import sys
import json
import uuid
import asyncio
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from jupyter_client.manager import AsyncKernelManager
from jupyter_client.kernelspec import NoSuchKernel
import structlog

from . import utils
from .docker_security import SecureDockerConfig, get_default_config

logger = structlog.get_logger(__name__)


class KernelLifecycle:
    """
    Manages the lifecycle of Jupyter kernel processes.
    
    Responsibilities:
    - Start kernels with proper environment configuration
    - Stop kernels gracefully
    - Restart kernels
    - Health checks
    - Docker container management
    - Resource limit enforcement
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
    
    def _validate_mount_path(self, project_root: Path) -> Path:
        """
        [SECURITY] Validate Docker mount path.
        
        Ensures the mount path is within allowed directories and doesn't
        escape via symlinks or .. traversal.
        
        IIRB COMPLIANCE: Blocks mounting of root (/) or system paths.
        """
        resolved_root = project_root.resolve()
        
        # [CRITICAL] Block mounting root or system paths
        # Check root separately (every path is relative to /)
        if resolved_root == Path('/'):
            raise ValueError(
                "SECURITY VIOLATION: Cannot mount root directory /. "
                "Mounting the root filesystem is forbidden."
            )
        
        # Block system paths (but allow /tmp for testing)
        dangerous_paths = [
            Path('/etc'), Path('/var'), Path('/usr'), 
            Path('/bin'), Path('/sbin'), Path('/boot'), Path('/sys')
        ]
        for dangerous in dangerous_paths:
            if resolved_root == dangerous or resolved_root.is_relative_to(dangerous):
                raise ValueError(
                    f"SECURITY VIOLATION: Cannot mount system path {resolved_root}. "
                    f"Mounting system directories is forbidden."
                )
        
        # Define allowed base paths (HOME and /tmp for testing)
        # Allow /tmp for pytest but maintain security for production
        # [P0 FIX #2] Use config-based data directory as fallback
        try:
            from src.config import load_and_validate_settings
            _cfg = load_and_validate_settings()
            default_allowed = _cfg.get_data_dir().parent if _cfg.MCP_DATA_DIR else Path.home()
        except Exception:
            default_allowed = Path.home()
        
        allowed_bases = [
            Path(os.environ.get("MCP_ALLOWED_ROOT", str(default_allowed))).resolve(),
            Path('/tmp').resolve()
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
                f"outside allowed bases {[str(b) for b in allowed_bases]}. "
                f"Set MCP_ALLOWED_ROOT environment variable to change this."
            )
        
        logger.info(f"[SECURITY] Validated mount path: {resolved_root}")
        return resolved_root
    
    def _configure_docker_kernel(
        self, 
        docker_image: str, 
        notebook_dir: Path,
        connection_file: str
    ) -> tuple[List[str], Dict[str, str], str]:
        """
        Configure kernel to run inside Docker container with production-grade security.
        
        Phase 3.2: Enhanced with SecureDockerConfig for defense-in-depth:
        - Seccomp profiles (blocks dangerous syscalls)
        - Capability dropping (minimal privilege set)
        - ulimits (resource constraints)
        - Read-only root filesystem
        - Network isolation
        
        Returns:
            (kernel_cmd, kernel_env, env_name)
        """
        # Locate workspace root for proper relative imports
        project_root = utils.get_project_root(notebook_dir)
        
        # Validate mount path to prevent path traversal
        project_root = self._validate_mount_path(project_root)
        
        mount_source = str(project_root)
        mount_target = "/workspace"
        
        # [SECURITY] Implement "Sandbox Subdirectory" pattern
        # Mount source code read-only, but provide a read-write sandbox for outputs.
        sandbox_dir = project_root / ".mcp_sandbox"
        sandbox_dir.mkdir(exist_ok=True)
        
        # Calculate CWD inside container
        container_cwd = "/workspace/sandbox"
        
        # [PHASE 3.2] Get production-grade security configuration
        security_config = get_default_config()
        security_config.validate()
        
        # Construct Docker Command with security hardening
        uid_args = ['-u', str(os.getuid())] if os.name != 'nt' else ['-u', '1000']
        
        cmd = [
            'docker', 'run', 
            '--rm',                     # Cleanup container on exit
            '-i',                       # Interactive (keeps stdin open)
        ] + security_config.to_docker_args() + [  # [PHASE 3.2] Security profiles
            # Mount source code read-only for reference
            '-v', f'{project_root}:/workspace/source:ro',
            # Mount sandbox read-write for assets/outputs
            '-v', f'{sandbox_dir}:/workspace/sandbox:rw',
            '-v', f'{connection_file}:/kernel.json:ro',
            '-w', container_cwd,        # CWD is the sandbox
        ] + uid_args + [
            docker_image,
            'python', '-m', 'ipykernel_launcher', '-f', '/kernel.json'
        ]
        
        logger.info(f"Configured Docker kernel with Phase 3.2 security: {' '.join(cmd[:15])}...")
        
        return cmd, {}, f"docker:{docker_image}"
    
    def _configure_local_kernel(
        self,
        venv_path: Optional[str] = None
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
        kernel_env['MCP_KERNEL_ID'] = kernel_uuid
        logger.info(f"[KERNEL] Assigning UUID: {kernel_uuid}")
        
        if venv_path:
            venv = Path(venv_path)
            if venv.exists():
                # Try bin/python (Unix) or Scripts/python.exe (Windows)
                py_exe_candidates = [
                    venv / "bin" / "python",
                    venv / "Scripts" / "python.exe"
                ]
                for candidate in py_exe_candidates:
                    if candidate.exists():
                        py_exe = str(candidate)
                        env_name = f"venv:{venv.name}"
                        logger.info(f"Using virtual environment: {venv_path}")
                        break
                else:
                    logger.warning(f"Virtual environment not found at {venv_path}, using system Python")
            else:
                logger.warning(f"Virtual environment path does not exist: {venv_path}")
        
        return py_exe, env_name, kernel_env
    
    async def start_kernel(
        self,
        kernel_id: str,
        notebook_dir: Path,
        venv_path: Optional[str] = None,
        docker_image: Optional[str] = None,
        agent_id: Optional[str] = None
    ) -> AsyncKernelManager:
        """
        Start a new Jupyter kernel.
        
        Args:
            kernel_id: Unique identifier for this kernel
            notebook_dir: Working directory for the kernel
            venv_path: Optional path to Python environment
            docker_image: Optional Docker image for sandboxing
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
            safe_agent = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(agent_id))
            agent_dir = notebook_dir / f"agent_{safe_agent}"
            agent_dir.mkdir(parents=True, exist_ok=True)
            notebook_dir = agent_dir
            logger.info(f"Agent CWD isolation: agent '{agent_id}' -> {notebook_dir}")
        
        km = AsyncKernelManager()
        
        if docker_image:
            # Docker mode
            connection_file = km.connection_file
            cmd, kernel_env, env_name = self._configure_docker_kernel(
                docker_image, notebook_dir, connection_file
            )
            km.kernel_cmd = cmd
            py_exe = "python"  # Inside container
        else:
            # Local mode
            py_exe, env_name, kernel_env = self._configure_local_kernel(venv_path)
            km.extra_env = kernel_env
        
        # Start the kernel
        await km.start_kernel(cwd=str(notebook_dir))

        # [WINDOWS PERMISSIONS FIX] Secure connection file on Windows
        if sys.platform == 'win32':
            try:
                import win32api
                import win32security
                import ntsecuritycon as con

                conn_file = km.connection_file
                user, _, _ = win32security.LookupAccountName("", win32api.GetUserName())
                
                sd = win32security.GetFileSecurity(conn_file, win32security.DACL_SECURITY_INFORMATION)
                dacl = win32security.ACL()
                dacl.AddAccessAllowedAce(win32security.ACL_REVISION, con.FILE_GENERIC_READ | con.FILE_GENERIC_WRITE, user)
                
                sd.SetSecurityDescriptorDacl(1, dacl, 0)
                win32security.SetFileSecurity(conn_file, win32security.DACL_SECURITY_INFORMATION, sd)
                logger.info(f"Secured connection file for Windows: {conn_file}")
            except ImportError:
                logger.warning("pywin32 not installed. Cannot set specific file permissions on Windows for connection file.")
            except Exception as e:
                logger.error(f"Failed to set Windows file permissions for connection file: {e}")

        # Track kernel metadata
        self.active_kernels[kernel_id] = {
            'km': km,
            'notebook_dir': str(notebook_dir),
            'python_exe': py_exe,
            'env_name': env_name,
            'docker_image': docker_image,
            'started_at': asyncio.get_event_loop().time()
        }
        
        logger.info(
            f"[KERNEL] Started {kernel_id}",
            env=env_name,
            docker=bool(docker_image),
            cwd=str(notebook_dir)
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
        
        kernel_info = self.active_kernels[kernel_id]
        km = kernel_info['km']
        
        try:
            await km.shutdown_kernel()
            logger.info(f"[KERNEL] Stopped {kernel_id}")
        except Exception as e:
            logger.error(f"[KERNEL] Error stopping {kernel_id}: {e}")
        finally:
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
        km = kernel_info['km']
        
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
        km = kernel_info['km']
        
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
            return {'alive': False, 'error': 'Kernel not found'}
        
        kernel_info = self.active_kernels[kernel_id]
        km = kernel_info['km']
        kc = km.client()
        
        if not kc.is_alive():
            return {'alive': False, 'error': 'Client not alive'}
        
        # Try kernel_info request with timeout
        import time
        start = time.time()
        try:
            await asyncio.wait_for(kc.kernel_info(), timeout=5.0)
            latency = (time.time() - start) * 1000
            return {'alive': True, 'latency_ms': round(latency, 2)}
        except asyncio.TimeoutError:
            return {'alive': False, 'error': 'Timeout waiting for kernel_info'}
        except Exception as e:
            return {'alive': False, 'error': str(e)}
