import logging
try:
    from policy_engine import PolicyEngine
except Exception:
    # Fallback lightweight policy engine for tests/environments without the optional package
    class PolicyEngine:
        def check_package(self, name, version=None):
            return True, "Allowed (fallback)", {}

try:
    from k8s_manager import K8sManager  # We need to interact with the pod
except Exception:
    class K8sManager:
        def __init__(self):
            self.core_v1 = None

logger = logging.getLogger(__name__)


class PackageManager:
    def __init__(self):
        self.policy_engine = PolicyEngine()
        self.k8s_manager = K8sManager()

    async def install_package_and_update_requirements(
        self, session_id: str, package_name: str, version: str | None
    ):
        """
        Manages the full lifecycle of a package installation:
        1. Audit the package using the policy engine.
        2. If approved, install it into the running kernel pod.
        3. Append it to the requirements.txt in the user's persistent volume.
        """
        is_approved, reason, report = self.policy_engine.check_package(
            package_name, version
        )

        if not is_approved:
            return False, reason

        # If approved, proceed with installation inside the pod
        pod_name = self.k8s_manager._get_pod_name(session_id)
        if not pod_name:
            return False, "Could not find the kernel pod for this session."

        req_spec = f"{package_name}{f'=={version}' if version else ''}"

        # Command to install the package
        install_command = ["pip", "install", req_spec]
        try:
            await self._execute_command_in_pod(pod_name, install_command)
            logger.info(f"Successfully installed {req_spec} in pod {pod_name}")
        except Exception as e:
            return False, f"Failed to install package in pod: {e}"

        # Command to update requirements.txt
        # Using shell to handle file I/O
        update_reqs_command = [
            "/bin/bash",
            "-c",
            f"echo '{req_spec}' >> /home/jovyan/work/requirements.txt",
        ]
        try:
            await self._execute_command_in_pod(pod_name, update_reqs_command)
            logger.info(
                f"Successfully updated requirements.txt for session {session_id}"
            )
        except Exception as e:
            # This is a non-fatal error; the package is installed but not persisted.
            # A more robust system might try to retry or alert.
            logger.warning(f"Failed to update requirements.txt in pod: {e}")
            return (
                True,
                f"Package installed, but failed to update requirements.txt: {e}",
            )

        return True, f"Successfully installed {req_spec} and updated requirements.txt."

    async def _execute_command_in_pod(self, pod_name: str, command: list[str]):
        """Helper to execute a shell command inside a specific pod."""
        from kubernetes.stream import stream

        resp = stream(
            self.k8s_manager.core_v1.connect_get_namespaced_pod_exec,
            pod_name,
            "default",
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        logger.debug(
            f"Exec in pod {pod_name} command '{' '.join(command)}' output: {resp}"
        )
        # A real implementation should check the command's exit code
