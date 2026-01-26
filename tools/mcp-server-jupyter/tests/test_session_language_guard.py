import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.session import SessionManager


@pytest.mark.asyncio
async def test_skip_python_injection_for_non_python_kernel():
    manager = SessionManager()

    with patch("src.session.AsyncKernelManager") as MockKM:
        km = MockKM.return_value
        km.start_kernel = AsyncMock()

        # Mock an "R" kernel
        km.kernel_name = "ir"  # R kernel name

        client = MagicMock()
        client.wait_for_ready = AsyncMock()
        client.start_channels = MagicMock()
        # We want to verify execute() is NOT called with startup code
        client.execute = MagicMock()
        km.client.return_value = client

        await manager.start_kernel("notebook.ipynb")

        # Make sure the startup injection block (IPython magics / helpers) wasn't sent
        for call in client.execute.call_args_list:
            code_sent = call[0][0]
            assert (
                "_mcp_inspect" not in code_sent
            ), "Python inspection helper injected into R kernel!"
            assert "%load_ext" not in code_sent, "IPython magic injected into R kernel!"
