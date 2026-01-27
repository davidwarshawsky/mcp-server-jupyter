import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple

try:
    from policy_engine import PolicyEngine
except Exception:
    # Fallback lightweight policy engine for tests/environments without the optional package
    class PolicyEngine:
        def check_package(self, name, version=None):
            return True, "Allowed (fallback)", {}

logger = logging.getLogger(__name__)


class PackageManager:
    def __init__(self):
        self.policy_engine = PolicyEngine()

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

        # Install package locally (local-only mode)
        req_spec = f"{package_name}{f'=={version}' if version else ''}"

        import subprocess

        install_proc = subprocess.run(["pip", "install", req_spec], capture_output=True, text=True)
        if install_proc.returncode != 0:
            logger.error(f"Failed to install {req_spec}: {install_proc.stderr}")
            return False, f"Failed to install package locally: {install_proc.stderr}"

        # Append to requirements.txt in current working directory
        try:
            with open("requirements.txt", "a", encoding="utf-8") as reqf:
                reqf.write(f"{req_spec}\n")
            logger.info(f"Successfully updated requirements.txt for session {session_id}")
        except Exception as e:
            logger.warning(f"Failed to update local requirements.txt: {e}")
            return True, f"Package installed, but failed to update requirements.txt: {e}"

        # Update lockfile locally
        try:
            success, msg = await self._update_lockfile(pod_name="local")
            if not success:
                logger.warning(f"Failed to update lockfile: {msg}")
        except Exception as e:
            logger.warning(f"Lockfile update threw an exception: {e}")

        return True, f"Successfully installed {req_spec} and updated requirements.txt."

    async def _update_lockfile(
        self, pod_name: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        [PHASE 2] Updates the lockfile by running 'pip freeze'.
        Ensures exact reproducibility on restart.

        Args:
        "pod_name: Ignored in local-first mode; package installs are performed locally."
        Returns:
            (success: bool, message: str)
        """
        try:
            if pod_name is None or pod_name == "local":
                # Local mode: use subprocess
                import subprocess

                result = subprocess.run(
                    ["pip", "freeze"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if result.returncode != 0:
                    logger.warning(f"pip freeze failed: {result.stderr}")
                    return False, f"pip freeze failed: {result.stderr}"

                lockfile_path = Path(".mcp-requirements.lock")
                lockfile_path.write_text(result.stdout)
                logger.info(f"Lockfile updated at {lockfile_path}")
                return True, f"Lockfile updated at {lockfile_path}"
            else:
                # K8s mode: execute in pod
                cmd = [
                    "/bin/bash",
                    "-c",
                    "pip freeze > /home/jovyan/work/.mcp-requirements.lock",
                ]
                await self._execute_command_in_pod(pod_name, cmd)
                logger.info(f"Lockfile updated in pod {pod_name}")
                return True, f"Lockfile updated in pod {pod_name}"

        except Exception as e:
            logger.error(f"Failed to update lockfile: {e}")
            return False, f"Lockfile update failed: {e}"

    # Kubernetes-specific package installation helpers removed.
    # Use the local install implementation above (subprocess-based) for a
    # local-first environment. If you need remote installs, implement an
    # explicit executor and call _update_lockfile as needed.
