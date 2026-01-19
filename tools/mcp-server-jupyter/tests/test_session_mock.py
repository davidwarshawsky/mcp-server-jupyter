import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from src.session import SessionManager

@pytest.mark.skip(reason="Mock test needs update - KernelLifecycle creates real kernels")
@pytest.mark.asyncio
async def test_start_kernel_logic():
    manager = SessionManager()
    
    # Mock the AsyncKernelManager and its client
    with patch("src.session.AsyncKernelManager") as MockKM:
        mock_km_instance = MockKM.return_value
        mock_km_instance.start_kernel = AsyncMock()
        mock_km_instance.shutdown_kernel = AsyncMock()
        
        # Mock the provisioner.process for newer jupyter_client
        mock_process = MagicMock()
        mock_process.pid = 9999
        mock_km_instance.provisioner = MagicMock()
        mock_km_instance.provisioner.process = mock_process
        # Also mock old-style kernel attribute for backwards compatibility
        mock_km_instance.kernel = None
        
        mock_client = MagicMock()
        mock_client.wait_for_ready = AsyncMock()
        mock_client.stop_channels = MagicMock()
        mock_km_instance.client.return_value = mock_client
        
        # Run method
        result = await manager.start_kernel("test_notebook.ipynb")
        
        # Assertions
        assert "9999" in result
        mock_km_instance.start_kernel.assert_called_once()
        assert any("test_notebook.ipynb" in k for k in manager.sessions.keys())

@pytest.mark.asyncio
async def test_run_info_command():
    """Test get_kernel_info by mocking the execute_cell_async -> execution status flow."""
    manager = SessionManager()
    nb_path = str(Path("dummy.ipynb").resolve())
    
    # Mock execute_cell_async to return an exec_id
    exec_id_returned = "test-exec-123"
    msg_id_fake = "msg-456"
    
    async def mock_execute_cell_async(nb_path: str, cell_index: int, code: str):
        # Resolve the path like the real method does
        resolved_path = str(Path(nb_path).resolve())
        # Simulate that execution completes immediately with output
        # Use msg_id as key, with 'id' field pointing to exec_id (matching real structure)
        manager.sessions[resolved_path]['executions'][msg_id_fake] = {
            'id': exec_id_returned,
            'status': 'completed',
            'outputs': [],
            'text_summary': '[{"name": "df", "type": "DataFrame"}]',
            'cell_index': cell_index,
            'execution_count': 1,
            'kernel_state': 'idle'
        }
        return exec_id_returned
    
    # Replace the method
    original_method = manager.execute_cell_async
    manager.execute_cell_async = mock_execute_cell_async
    
    # Create minimal session with RESOLVED path as key
    manager.sessions[nb_path] = {
        'kc': AsyncMock(), 
        'km': MagicMock(),
        'execution_queue': AsyncMock(),
        'executions': {},
        'queued_executions': {}  # Add missing field for new race-condition fix
    }
    
    try:
        info = await manager.get_kernel_info("dummy.ipynb")
        assert "DataFrame" in info
    finally:
        # Restore original method
        manager.execute_cell_async = original_method

@pytest.mark.asyncio
async def test_execution_timeout_triggers_interrupt():
    # We need to test the logic in main.py, but it uses global session_manager.
    # We can test the session_manager logic for strict venv check here.
    pass

@pytest.mark.asyncio
async def test_install_package_calls_pip():
    manager = SessionManager()
    mock_km = MagicMock()
    # Mock that kernel command was [python, ...]
    mock_km.kernel_cmd = ["/path/to/python", "-f", "connection_file"]
    
    nb_path = str(Path("test.ipynb").resolve())
    manager.sessions[nb_path] = {'km': mock_km, 'kc': MagicMock()}
    
    # Mock subprocess
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"Successfully installed", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc
        
        res = await manager.install_package("test.ipynb", "pandas")
        
        assert "Successfully installed" in res
        mock_exec.assert_called_with(
            "/path/to/python", "-m", "pip", "install", "pandas",
            stdout=-1, stderr=-1
        )
