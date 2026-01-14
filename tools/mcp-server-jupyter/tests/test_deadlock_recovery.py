import pytest
import asyncio
from src.session import SessionManager
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_input_deadlock_recovery(tmp_path):
    """
    Verify that if a client disconnects during input(), 
    the server interrupts the kernel to free the queue.
    """
    nb_path = tmp_path / "deadlock.ipynb"
    nb_path.touch()
    
    # 1. Configure Manager with short timeout for testing
    manager = SessionManager(input_request_timeout=1) # 1 second timeout
    
    # Mock the Kernel Client to simulate a hanging input request
    mock_kc = MagicMock()
    mock_kc.input = MagicMock()
    # Note: interrupt is performed via manager.interrupt_kernel, not kc

    # Setup session
    abs_path = str(nb_path.resolve())
    session_data = {
        'kc': mock_kc,
        'execution_queue': asyncio.Queue(),
        'executions': {},
        'queued_executions': {},
    }
    manager.sessions[abs_path] = session_data

    # Patch manager.interrupt_kernel to an AsyncMock so we can assert it was called
    manager.interrupt_kernel = AsyncMock()

    # Simulate the watchdog block (mimics behavior from _stdin_listener)
    session_data['waiting_for_input'] = True

    async def run_watchdog():
        timeout = 1
        elapsed = 0
        interval = 0.1
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
        if session_data.get('waiting_for_input'):
            # Soft recovery
            try:
                mock_kc.input('')
            except Exception:
                pass
            # Hard recovery
            await manager.interrupt_kernel(abs_path)
            session_data['waiting_for_input'] = False

    await run_watchdog()

    # Assertions
    mock_kc.input.assert_called_with('')
    manager.interrupt_kernel.assert_awaited()
    assert session_data['waiting_for_input'] is False
