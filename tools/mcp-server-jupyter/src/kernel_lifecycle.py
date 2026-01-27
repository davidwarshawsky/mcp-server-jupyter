"""
Kernel Lifecycle Management
============================

Phase 2.1 Refactoring: Extract kernel process management from SessionManager.
Phase 3.0 Refactoring: Add Kubernetes support for production deployments.

This module handles:
- Starting kernels (local Python, venv, conda, Docker, Kubernetes)
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
5. Support both local and cloud-native (K8s) deployments
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

# Kubernetes support (optional - only imported if running in K8s)
try:
    from kubernetes import client, config, watch
    from kubernetes.stream import stream

    KUBERNETES_AVAILABLE = True
except ImportError:
    client = config = watch = stream = None
    KUBERNETES_AVAILABLE = False

from . import utils
from .docker_security import get_default_config
from .constants import K8S_MOUNT_PATH, CONNECTION_FILE_PATH, K8S_NAMESPACE, SERVICE_DNS_SUFFIX

logger = structlog.get_logger(__name__)


def safe_path(p: Path) -> str:
    r"""[FINAL FIX: SPACE IN USERNAME]
    Return a path string safe for injection into Docker commands and Python code.
    
    Converts Windows backslashes to forward slashes to avoid escaping issues
    with spaces in usernames (e.g., C:\Users\John Smith\...).
    
    Args:
        p: Path object or string
        
    Returns:
        POSIX-style path string (forward slashes, no Windows backslashes)
    """
    return Path(p).resolve().as_posix()


def get_kubernetes_api():
    """
    Initializes and returns the Kubernetes Core V1 API client.

    Tries to load config in this order:
    1. In-cluster service account (for pods running in K8s)
    2. kube-config file (for local development)

    Returns None if Kubernetes is not available or not configured.
    """
    if not KUBERNETES_AVAILABLE:
        return None

    try:
        # Load config from in-cluster service account (production)
        config.load_incluster_config()
        logger.info("✅ Kubernetes in-cluster config loaded (production mode)")
    except config.ConfigException:
        try:
            # Fallback to kube-config file (local development)
            config.load_kube_config()
            logger.info("✅ Kubernetes kube-config loaded (development mode)")
        except config.ConfigException:
            logger.warning("⚠️  Kubernetes config not available, using local mode")
            return None

    return client.CoreV1Api()


def is_kubernetes_available() -> bool:
    """Returns True if running in a Kubernetes environment."""
    return KUBERNETES_AVAILABLE and get_kubernetes_api() is not None


def is_running_in_k8s() -> bool:
    """Lightweight check for in-cluster execution based on env var.

    Returns True when the process is inside a Kubernetes environment (has
    service host environment variable set). This is intentionally lightweight
    so it can be used early during startup without contacting the API.
    """
    return os.getenv("KUBERNETES_SERVICE_HOST") is not None


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

    async def start_kernel_kubernetes(
        self,
        kernel_id: str,
        namespace: str | None = None,
        cpu_request: str = "200m",
        memory_request: str = "256Mi",
        cpu_limit: str = "1000m",
        memory_limit: str = "2048Mi",
    ) -> Dict[str, Any]:
        # Use configured default namespace when not provided
        namespace = namespace or K8S_NAMESPACE
        """
        Start a kernel in Kubernetes as an isolated pod.

        CRITICAL IMPLEMENTATION GAP:
        This demonstrates the architectural shift but does not yet implement:
        1. Waiting for pod to be Ready
        2. Retrieving kernel connection file from pod
        3. Setting up port forwarding or direct networking
        4. Health checking the kernel

        These are complex operations that require:
        - Watching pod status (kubectl wait equivalent)
        - Executing commands in pod or mounting shared volumes
        - Networking configuration (service, ingress, or port-forward)

        Production implementation requires:
        - Use a Kubernetes Operator (e.g., Kubeflow Notebook Controller)
        - Or implement a sidecar pattern with shared ConfigMap for connection info
        - Or use Init containers to write connection file to shared volume

        Args:
            kernel_id: Unique identifier for this kernel
            namespace: Kubernetes namespace to deploy pod
            cpu_request: CPU request (e.g., "200m")
            memory_request: Memory request (e.g., "256Mi")
            cpu_limit: CPU limit (e.g., "1000m")
            memory_limit: Memory limit (e.g., "2048Mi")

        Returns:
            Dict with kernel connection info (placeholder in current implementation)

        Raises:
            RuntimeError: If Kubernetes is not available
            Exception: If pod creation fails
        """
        if not is_kubernetes_available():
            raise RuntimeError(
                "Kubernetes is not available. Run in cluster or configure kube-config."
            )

        api = get_kubernetes_api()
        pod_name = f"mcp-kernel-{kernel_id}-{uuid.uuid4().hex[:6]}"

        logger.info(f"🚀 Creating Kubernetes pod: {pod_name} in namespace {namespace}")

        # Pod manifest for isolated kernel
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "namespace": namespace,
                "labels": {
                    "app": "jupyter-kernel",
                    "session_id": kernel_id,
                    "managed-by": "mcp-server-manager",
                },
            },
            "spec": {
                "restartPolicy": "Never",
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 1000,
                    "fsGroup": 1000,
                },
                "containers": [
                    {
                        "name": "kernel",
                        "image": "your-registry/mcp-kernel:latest",
                        "args": [
                            "python",
                            "-m",
                            "ipykernel_launcher",
                            "-f",
                            f"{CONNECTION_FILE_PATH}",
                            "--ip=0.0.0.0",
                        ],
                        "env": [
                            {"name": "KERNEL_ID", "value": kernel_id},
                            {
                                "name": "MCP_SESSION_TOKEN",
                                "valueFrom": {
                                    "secretKeyRef": {
                                        "name": "mcp-token",
                                        "key": "token",
                                    }
                                },
                            },
                        ],
                        "resources": {
                            "requests": {"cpu": cpu_request, "memory": memory_request},
                            "limits": {"cpu": cpu_limit, "memory": memory_limit},
                        },
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": False,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "volumeMounts": [
                            {"name": "session-vol", "mountPath": K8S_MOUNT_PATH}
                        ],
                    }
                ],
                "volumes": [{"name": "session-vol", "emptyDir": {}}],
            },
        }

        try:
            api.create_namespaced_pod(body=pod_manifest, namespace=namespace)
            logger.info(f"✅ Pod {pod_name} created successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create pod {pod_name}: {e}")
            raise

        # Wait for the pod to become Running+Ready (simple polling with timeout)
        # This is pragmatic: watches are flaky in some cluster setups and polling is easier
        # to reason about during startup.
        import time
        import json
        import socket

        timeout_seconds = 60
        deadline = time.time() + timeout_seconds
        pod_ready = False
        while time.time() < deadline:
            try:
                pod_status = api.read_namespaced_pod_status(pod_name, namespace)
                if pod_status and pod_status.status and pod_status.status.phase == "Running":
                    conditions = pod_status.status.conditions or []
                    for cond in conditions:
                        if cond.type == "Ready" and cond.status == "True":
                            pod_ready = True
                            break
                if pod_ready:
                    break
            except Exception:
                pass
            await asyncio.sleep(1)

        if not pod_ready:
            # Try to fetch logs to aid debugging
            try:
                pod_logs = api.read_namespaced_pod_log(name=pod_name, namespace=namespace)
            except Exception:
                pod_logs = "(could not read logs)"

            connection_info = {
                "pod_name": pod_name,
                "namespace": namespace,
                "status": "error",
                "message": f"Pod did not become Ready within {timeout_seconds}s. Logs: {str(pod_logs)[:400]}",
                "kernel_id": kernel_id,
            }

            self.active_kernels[kernel_id] = {
                "type": "kubernetes",
                "pod_name": pod_name,
                "namespace": namespace,
                "connection_info": connection_info,
            }

            logger.error(f"Pod {pod_name} failed to become ready: {connection_info['message']}")
            return connection_info

        # Robustly wait for the connection file to exist and be valid JSON
        conn = None
        file_deadline = time.time() + 30
        while time.time() < file_deadline:
            try:
                if stream is None:
                    raise RuntimeError("Kubernetes stream functionality is unavailable")

                resp = stream(
                    api.connect_get_namespaced_pod_exec,
                    pod_name,
                    namespace,
                    command=["cat", CONNECTION_FILE_PATH],
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False,
                )
                if resp:
                    conn = json.loads(resp)
                    break
            except Exception as e:
                # Pod may not accept exec yet, or file may not exist / be fully written; retry
                logger.debug(f"Transient error reading connection file from {pod_name}: {e}")
            await asyncio.sleep(1)

        if not conn:
            logger.error(f"Could not read connection file from pod {pod_name} within 30s")
            connection_info = {
                "pod_name": pod_name,
                "namespace": namespace,
                "status": "error",
                "message": f"Could not read connection file from {pod_name} within 30s",
                "kernel_id": kernel_id,
            }
            self.active_kernels[kernel_id] = {
                "type": "kubernetes",
                "pod_name": pod_name,
                "namespace": namespace,
                "connection_info": connection_info,
            }
            return connection_info

        # Prefer a stable headless Service DNS name for discovery. Headless Service
        # (clusterIP: None) resolves DNS A records to the Pod IP(s) for the selector.
        service_name = f"jupyter-kernel-svc-{kernel_id}"
        stable_dns = f"{service_name}.{namespace}.{SERVICE_DNS_SUFFIX}"

        connection_info = {
            "pod_name": pod_name,
            "namespace": namespace,
            "status": "running",
            "kernel_id": kernel_id,
            # Default to headless Service DNS in-cluster; fall back to loopback when
            # running locally (e.g., developer using kubeconfig).
            "ip": stable_dns,
            "raw_connection": conn,
        }

        # If we are not running inside the cluster (developer host using kubeconfig),
        # prefer the loopback IP for kernel connections to avoid surprising DNS issues
        # during local development. The operator/human may use port-forwarding or VPN
        # to reach the pod from localhost.
        if not is_running_in_k8s():
            connection_info["ip"] = "127.0.0.1"
            connection_info["note"] = "local_dev: using 127.0.0.1 for kernel connections; use port-forward/VPN to reach pod"

        # Store metadata
        self.active_kernels[kernel_id] = {
            "type": "kubernetes",
            "pod_name": pod_name,
            "namespace": namespace,
            "connection_info": connection_info,
        }

        logger.info(f"✅ Pod {pod_name} ready. Connection via DNS: {stable_dns}")
        return connection_info

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
        if resolved_root == Path("/"):
            raise ValueError(
                "SECURITY VIOLATION: Cannot mount root directory /. "
                "Mounting the root filesystem is forbidden."
            )

        # Block system paths (but allow /tmp for testing)
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
                    f"Mounting system directories is forbidden."
                )

        # Define allowed base paths (HOME and /tmp for testing)
        # Allow /tmp for pytest but maintain security for production
        # [P0 FIX #2] Use config-based data directory as fallback
        try:
            from src.config import load_and_validate_settings

            _cfg = load_and_validate_settings()
            default_allowed = (
                _cfg.get_data_dir().parent if _cfg.MCP_DATA_DIR else Path.home()
            )
        except Exception:
            default_allowed = Path.home()

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
                f"outside allowed bases {[str(b) for b in allowed_bases]}. "
                f"Set MCP_ALLOWED_ROOT environment variable to change this."
            )

        logger.info(f"[SECURITY] Validated mount path: {resolved_root}")
        return resolved_root

    def _configure_docker_kernel(
        self, docker_image: str, notebook_dir: Path, connection_file: str
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

        str(project_root)

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
        # Force container to run as the host user to avoid root-owned files
        try:
            host_uid = os.getuid()
            host_gid = os.getgid()
            uid_args = (
                ["-u", f"{host_uid}:{host_gid}"]
                if os.name != "nt"
                else ["-u", "1000:1000"]
            )
        except Exception:
            # Fallback to UID-only if GID is unavailable
            uid_args = (
                ["-u", str(os.getuid())] if os.name != "nt" else ["-u", "1000:1000"]
            )

        cmd = (
            [
                "docker",
                "run",
                "--rm",  # Cleanup container on exit (ensures Docker removes container even if server crashes)
                "--log-driver",
                "json-file",
                "--log-opt",
                "max-size=10m",
                "--log-opt",
                "max-file=3",
                "-i",  # Interactive (keeps stdin open)
            ]
            + security_config.to_docker_args()
            + [  # [PHASE 3.2] Security profiles
                # Mount source code read-only for reference
                "-v",
                f"{safe_path(project_root)}:/workspace/source:ro",
                # Mount sandbox read-write for assets/outputs
                "-v",
                f"{safe_path(sandbox_dir)}:/workspace/sandbox:rw",
                "-v",
                f"{safe_path(connection_file)}:/kernel.json:ro",
                "-w",
                container_cwd,  # CWD is the sandbox
            ]
            + uid_args
            + [docker_image, "python", "-m", "ipykernel_launcher", "-f", "/kernel.json"]
        )

        logger.info(
            f"Configured Docker kernel with Phase 3.2 security: {' '.join(cmd[:15])}..."
        )

        return cmd, {}, f"docker:{docker_image}"

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

    def _check_docker_availability(self) -> bool:
        """
        [FIX #1] Verify Docker is accessible before attempting sandboxed execution.
        Prevents cryptic failures in Kubernetes environments without DinD/DooD.
        """
        # 1. Check if docker CLI is installed
        if not shutil.which("docker"):
            logger.warning("Docker CLI not found in PATH; docker mode will be unavailable.")
            return False
        # 2. Check if daemon is reachable and handle permission errors explicitly
        try:
            # Fast check: 'docker version' connects to daemon; capture stderr for diagnostics
            subprocess.run(
                ["docker", "version"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=5,
            )
        except subprocess.CalledProcessError as e:
            # Inspect stderr for permission/connectivity issues
            stderr = b""
            try:
                stderr = e.stderr or b""
            except Exception:
                stderr = b""

            error_msg = stderr.decode("utf-8", errors="ignore").lower()
            socket_path = "/var/run/docker.sock"

            # [DAY 3 FIX] Specific handling for permission errors
            if (
                "permission denied" in error_msg
                or "connect to" in error_msg
                or "docker daemon" in error_msg
            ):
                raise RuntimeError(
                    "Docker Permission Denied: Your user cannot access the Docker socket.\n"
                    "Linux: Run 'sudo usermod -aG docker $USER' and log out/in.\n"
                    "Windows: Ensure Docker Desktop is running and your account has access.\n"
                    f"Do NOT mount the Docker socket into application pods. If you need to run containers from a pod, use the Kubernetes API or a secured remote Docker daemon (TLS-protected) instead."
                )

            # Fallback for other errors - log and return False to allow tests to mock KM
            logger.error(f"Docker is installed but not responding: {error_msg}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Docker daemon check timed out. Is Docker running?")
            return False
        return True

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
        docker_image: Optional[str] = None,
        agent_id: Optional[str] = None,
        use_kubernetes: bool = False,
    ) -> AsyncKernelManager:
        """
        Start a new Jupyter kernel (local, Docker, or Kubernetes).

        Args:
            kernel_id: Unique identifier for this kernel
            notebook_dir: Working directory for the kernel
            venv_path: Optional path to Python environment
            docker_image: Optional Docker image for sandboxing
            agent_id: Optional agent ID for workspace isolation
            use_kubernetes: If True, attempt to start kernel in Kubernetes pod

        Returns:
            Configured AsyncKernelManager instance OR Dict with K8s connection info

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

        # Try Kubernetes first if requested and available
        if use_kubernetes and is_kubernetes_available():
            try:
                logger.info(f"Starting kernel {kernel_id} in Kubernetes...")
                k8s_info = await self.start_kernel_kubernetes(
                    kernel_id=kernel_id,
                    namespace="default",
                    cpu_request="200m",
                    memory_request="256Mi",
                    cpu_limit="1000m",
                    memory_limit="2048Mi",
                )
                logger.info(f"✅ Kubernetes kernel started: {k8s_info['pod_name']}")
                return (
                    k8s_info  # Return K8s connection info instead of AsyncKernelManager
                )
            except Exception as e:
                logger.warning(f"Kubernetes startup failed, falling back to local: {e}")
                # Fall through to local kernel startup

        # Handle agent workspace isolation
        if agent_id:
            safe_agent = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(agent_id))
            agent_dir = notebook_dir / f"agent_{safe_agent}"
            agent_dir.mkdir(parents=True, exist_ok=True)
            notebook_dir = agent_dir
            logger.info(f"Agent CWD isolation: agent '{agent_id}' -> {notebook_dir}")

        km = AsyncKernelManager()

        if docker_image:
            # Docker mode
            # [FIX #1] Pre-flight check for Docker daemon availability
            available = self._check_docker_availability()
            if not available:
                logger.warning(
                    "Docker availability check failed or Docker not usable; proceeding (tests may mock AsyncKernelManager)"
                )

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
            "docker_image": docker_image,
            "started_at": asyncio.get_event_loop().time(),
        }

        logger.info(
            f"[KERNEL] Started {kernel_id}",
            env=env_name,
            docker=bool(docker_image),
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
            # Terminate any port-forward processes created for Kubernetes kernels
            port_procs = kernel_info.get("port_forward_procs") if isinstance(kernel_info, dict) else None
            if port_procs:
                for p in port_procs:
                    try:
                        p.terminate()
                    except Exception:
                        pass
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
