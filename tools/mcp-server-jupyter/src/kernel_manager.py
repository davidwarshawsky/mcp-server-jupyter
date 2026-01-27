import asyncio
import logging
import time
from jupyter_client import AsyncKernelClient

# Kubernetes manager removed — local-only mode (no external orchestration)

logger = logging.getLogger(__name__)


class KernelManager:
    """
    A stateless manager for Jupyter kernels (local-only).
    Kubernetes orchestration support was removed as part of the local-first pivot.
    Methods that depended on cluster APIs will raise informative errors.
    """

    def __init__(self):
        # Kubernetes orchestration removed; keep placeholder attributes for compatibility
        self.k8s_manager = None
        self.active_sessions = set()  # Still useful for tracking, but not for state

    async def _get_client_for_session(self, session_id: str) -> AsyncKernelClient:
        """Creates and configures a kernel client for a given session ID."""
        # Kubernetes-based client retrieval removed. Use local kernel start pathways.
        raise RuntimeError("Kubernetes-based kernel client retrieval removed: use local kernel startup pathways.")

    async def start_kernel_for_session(self, session_id: str):
        """
        Ensures Kubernetes resources are created for a session and marks it as active.
        """
        # Kubernetes orchestration removed — this method is not supported in local-only builds.
        raise RuntimeError("Kubernetes orchestration removed: start_kernel_for_session is unavailable.")

    async def execute_code(self, session_id: str, code: str) -> dict:
        """Executes code in the kernel for the given session."""
        if session_id not in self.active_sessions:
            raise ValueError(f"Session {session_id} not found or not active.")

        client = await self._get_client_for_session(session_id)

        try:
            client.execute(code)
            # In a real implementation, you would listen for the specific reply
            # to this msg_id on the IOPub and Shell channels.
            # For now, we'll do a simplified wait for some output.
            await asyncio.sleep(1)  # Simplified wait
            # This is a placeholder for a more robust result handling mechanism
            return {
                "status": "ok",
                "output": "Execution sent, result handling not fully implemented.",
            }
        finally:
            client.stop_channels()

    def shutdown_kernel(self, session_id: str):
        """Shuts down and cleans up all resources for a kernel session."""
        logger.info(f"Shutting down kernel and resources for session {session_id}")
        # Kubernetes-based shutdown is not applicable in local-only builds.
        self.active_sessions.discard(session_id)
        logger.info(f"Cleaned up session {session_id} (local-only).")

    async def _wait_for_pod_ready(self, session_id: str, timeout=120):
        """Waits for the kernel pod to be in a 'Running' state."""
        raise RuntimeError("Kubernetes pod readiness checks removed: local-only deployments do not use pods.")
