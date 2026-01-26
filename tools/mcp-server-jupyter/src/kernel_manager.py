import asyncio
import logging
import time
from jupyter_client import AsyncKernelClient

from src.k8s_manager import K8sManager

logger = logging.getLogger(__name__)


class KernelManager:
    """
    A stateless manager for Jupyter kernels running in Kubernetes.
    It does not hold kernel clients in memory. Instead, it recreates them
    on-demand using connection information fetched directly from the Kubernetes pod.
    """

    def __init__(self):
        self.k8s_manager = K8sManager()
        self.active_sessions = set()  # Still useful for tracking, but not for state

    async def _get_client_for_session(self, session_id: str) -> AsyncKernelClient:
        """Creates and configures a kernel client for a given session ID."""
        connection_info = self.k8s_manager.get_kernel_connection_info(session_id)

        client = AsyncKernelClient()
        client.connection_file = ""  # Not reading from a file
        client.load_connection_info(connection_info)
        client.start_channels()

        # Wait for the client to be fully ready
        await client.wait_for_ready(timeout=60)

        return client

    async def start_kernel_for_session(self, session_id: str):
        """
        Ensures Kubernetes resources are created for a session and marks it as active.
        """
        logger.info(f"Initiating kernel resources for session {session_id}")
        self.k8s_manager.create_kernel_resources(session_id)
        # Await pod readiness before proceeding
        await self._wait_for_pod_ready(session_id)
        self.active_sessions.add(session_id)
        logger.info(f"Session {session_id} is now active.")

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
        try:
            self.k8s_manager.delete_kernel_resources(session_id)
            self.active_sessions.discard(session_id)
            logger.info(f"Successfully cleaned up resources for session {session_id}")
        except Exception as e:
            logger.error(f"Error during shutdown for session {session_id}: {e}")

    async def _wait_for_pod_ready(self, session_id: str, timeout=120):
        """Waits for the kernel pod to be in a 'Running' state."""
        logger.info(f"Waiting for pod to be ready for session {session_id}...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            pod_name = self.k8s_manager._get_pod_name(session_id)
            if pod_name:
                pod_status = self.k8s_manager.core_v1.read_namespaced_pod_status(
                    name=pod_name, namespace="default"
                ).status.phase
                if pod_status == "Running":
                    logger.info(f"Pod for session {session_id} is Running.")
                    # Even if running, the jupyter process inside might need a moment
                    await asyncio.sleep(5)
                    return
            await asyncio.sleep(2)  # Check every 2 seconds
        raise TimeoutError(
            f"Pod for session {session_id} did not become ready within {timeout} seconds."
        )
