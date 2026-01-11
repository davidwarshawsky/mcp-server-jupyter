import pytest
import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from src.main import ConnectionManager

@pytest.mark.asyncio
async def test_broadcast_resilience():
    """
    Critical Test: Ensure one dead client doesn't crash the stream for the living client.
    """
    manager = ConnectionManager()
    
    # Mock Client A (The Agent - Healthy)
    client_a = AsyncMock()
    client_a.send_text = AsyncMock()
    
    # Mock Client B (VS Code - Disconnected/Crashed)
    client_b = AsyncMock()
    # Simulate a broken pipe or connection lost error
    client_b.send_text.side_effect = Exception("Connection lost")
    
    # Manually add them to active connections (bypassing accept await)
    manager.active_connections = [client_a, client_b]
    
    # Broadcast a message
    msg = {"method": "notebook/output", "params": {"data": "test"}}
    await manager.broadcast(msg)
    
    # Assertions
    # 1. Client A should have received the message
    client_a.send_text.assert_called_once()
    
    # 2. Client B should have triggered the exception handling
    # 3. Client B should be removed from the active list (Self-Healing)
    assert client_b not in manager.active_connections
    assert client_a in manager.active_connections
    assert len(manager.active_connections) == 1

@pytest.mark.asyncio
async def test_interactive_input_flow():
    """
    Critical Test: Verify the round-trip logic of Input Request.
    """
    from src.session import SessionManager
    
    # Setup Mocks
    sm = SessionManager()
    sm.connection_manager = AsyncMock()
    
    # Mock Kernel Client Stdin
    # Use spec=['input'] to ensure we strictly mimic the needed interface
    # and guarantee no other ZMQ methods (like execute/shell_channel) are accessed.
    mock_kc = MagicMock(spec=['input'])
    mock_kc.input = MagicMock(return_value=None)
    
    # Use resolved path for the key, as get_session does
    test_path = "test.ipynb"
    abs_path = str(Path(test_path).resolve())
    
    # Inject session
    sm.sessions[abs_path] = {
        "kc": mock_kc,
        "env_info": {},
         # Session needs execution queue logic if submit input does check it, 
         # but let's check basic logic first
    }
    
    # 2. Test Response Submission (Client -> Kernel)
    # The actual implementation of submit_input uses kc.input(text)
    await sm.submit_input("test.ipynb", "password123")
    
    # Verify the input was sent to the kernel ZMQ channel
    mock_kc.input.assert_called_with("password123")
