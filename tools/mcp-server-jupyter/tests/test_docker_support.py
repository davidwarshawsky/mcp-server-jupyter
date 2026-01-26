import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import os
from src.session import SessionManager


@pytest.mark.asyncio
async def test_start_kernel_docker_config(tmp_path, monkeypatch):
    """
    Verify that start_kernel generates a secure 'docker run' command
    with network disabled and correct user mapping.
    Reference: Review Point 3 - "Docker Support is an Un-tested Lie"
    """
    # Allow tmp_path as valid mount root for Docker
    monkeypatch.setenv("MCP_ALLOWED_ROOT", str(tmp_path))

    manager = SessionManager()

    # Mock AsyncKernelManager in BOTH session.py and kernel_lifecycle.py
    # since the refactored code delegates to kernel_lifecycle
    with patch("src.kernel_lifecycle.AsyncKernelManager") as MockKM_lifecycle, patch(
        "src.session.AsyncKernelManager"
    ) as MockKM_session:
        # Setup the mock km instance that will be returned
        km_instance = MagicMock()
        km_instance.start_kernel = AsyncMock()
        km_instance.has_kernel = True
        km_instance.kernel_cmd = []  # Will be set by the code

        # Mock kernel process for PID
        mock_provisioner = MagicMock()
        mock_provisioner.process = MagicMock()
        mock_provisioner.process.pid = 12345
        km_instance.provisioner = mock_provisioner
        km_instance.kernel = None
        km_instance.connection_file = "/tmp/fake_connection.json"

        mock_client = MagicMock()
        mock_client.wait_for_ready = AsyncMock()
        mock_client.execute = MagicMock(return_value="msg_123")
        mock_client.get_iopub_msg = AsyncMock(side_effect=TimeoutError)
        km_instance.client.return_value = mock_client

        MockKM_lifecycle.return_value = km_instance
        MockKM_session.return_value = km_instance

        # Use real temp directory to avoid Path.resolve mocking issues
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        nb_path = project_dir / "notebook.ipynb"
        nb_path.write_text("{}")  # Create empty notebook file

        docker_image = "my-secure-image:latest"

        expected_uid = str(os.getuid())

        await manager.start_kernel(str(nb_path), docker_image=docker_image)

        cmd = km_instance.kernel_cmd

        # Assertions for Reviewer Requirements
        assert "docker" in cmd
        assert "run" in cmd

        # Security: Network Isolation
        assert "--network" in cmd
        network_idx = cmd.index("--network")
        assert cmd[network_idx + 1] == "none", "Docker must run with --network none"

        # Security: User Mapping
        assert "-u" in cmd
        uid_idx = cmd.index("-u")
        assert cmd[uid_idx + 1] == expected_uid, "Docker must run as current UID"

        # Image
        assert docker_image in cmd

        # Ensure we added --init so signals propagate correctly
        assert (
            "--init" in cmd
        ), "Docker command missing --init (Signal propagation will fail)"

        # Metadata check (Regression fix)
        session = manager.sessions[str(nb_path.resolve())]
        assert session["env_info"]["env_name"] == f"docker:{docker_image}"
