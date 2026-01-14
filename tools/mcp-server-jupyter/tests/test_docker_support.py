
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import os
from pathlib import Path
from src.session import SessionManager

@pytest.mark.asyncio
async def test_start_kernel_docker_config():
    """
    Verify that start_kernel generates a secure 'docker run' command
    with network disabled and correct user mapping.
    Reference: Review Point 3 - "Docker Support is an Un-tested Lie"
    """
    manager = SessionManager()
    
    with patch("src.session.AsyncKernelManager") as MockKM:
        km_instance = MockKM.return_value
        km_instance.start_kernel = AsyncMock()
        km_instance.has_kernel = False
        
        mock_client = MagicMock()
        mock_client.wait_for_ready = AsyncMock()
        km_instance.client.return_value = mock_client
        
        # Test Parameters
        nb_path = "/home/user/project/notebook.ipynb"
        docker_image = "my-secure-image:latest"
        
        expected_uid = str(os.getuid())
        
        # Mock Path resolution to ensure stable paths in test
        with patch("pathlib.Path.resolve", return_value=Path("/home/user/project/notebook.ipynb")):
             
             await manager.start_kernel(
                 nb_path, 
                 docker_image=docker_image
             )
             
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
             assert "--init" in cmd, "Docker command missing --init (Signal propagation will fail)"
             
             # Metadata check (Regression fix)
             session = manager.sessions[str(Path(nb_path))]
             assert session['env_info']['env_name'] == f"docker:{docker_image}"
