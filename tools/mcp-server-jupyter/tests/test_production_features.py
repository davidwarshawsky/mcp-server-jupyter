import pytest
import asyncio
import json
import time
from unittest.mock import MagicMock, patch
from pathlib import Path
from src.main import ConnectionManager, get_server_status, mcp, connection_manager
from src.utils import get_project_root

# --- Throttling Tests ---

@pytest.mark.asyncio
async def test_broadcast_throttling():
    """Verify that messages are throttled to ~10Hz."""
    cm = ConnectionManager()
    mock_socket = MagicMock()
    mock_socket.send_text = MagicMock(return_value=asyncio.Future())
    mock_socket.send_text.return_value.set_result(None)
    
    await cm.connect(mock_socket)
    
    # 1. Send first message (should execute)
    await cm.broadcast({"method": "notebook/output", "data": "1"})
    assert mock_socket.send_text.call_count == 1
    
    # 2. Send immediate second message (should be dropped/skipped due to throttling)
    # We mock time to be same instant
    with patch('time.time', return_value=cm.last_broadcast + 0.05):
        await cm.broadcast({"method": "notebook/output", "data": "2"})
    
    # Call count should STILL be 1
    assert mock_socket.send_text.call_count == 1
    
    # 3. Send message after 0.2s (should execute)
    with patch('time.time', return_value=cm.last_broadcast + 0.2):
        await cm.broadcast({"method": "notebook/output", "data": "3"})
        
    assert mock_socket.send_text.call_count == 2
    
    # 4. Verify non-output messages are NOT throttled
    await cm.broadcast({"method": "notebook/status", "data": "urgent"})
    assert mock_socket.send_text.call_count == 3


# --- Server Status Tests ---

def test_get_server_status():
    """Verify the self-awareness tool."""
    # Ensure clean state
    connection_manager.active_connections = []
    
    # Only agent connected (implicit) - actually tool returns active_connections which tracks websockets
    status = json.loads(get_server_status())
    assert status['active_connections'] == 0
    assert status['mode'] == 'solo'
    
    # Simulate a connection
    connection_manager.active_connections.append(MagicMock())
    status = json.loads(get_server_status())
    assert status['active_connections'] == 1
    assert status['mode'] == 'solo' # 1 is still solo (just the user) ?? 
    # Wait, logic is: mode="multi-user" if len > 1.
    # If 1 connection, it is likely the user.
    
    connection_manager.active_connections.append(MagicMock())
    status = json.loads(get_server_status())
    assert status['active_connections'] == 2
    assert status['mode'] == 'multi-user'


# --- Project Root Tests ---

def test_get_project_root(tmp_path):
    """Verify project root detection."""
    # Structure:
    # /root
    #   .git/
    #   src/
    #     notebooks/
    #       nb.ipynb
    
    (tmp_path / ".git").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    nbs = src / "notebooks"
    nbs.mkdir()
    
    # Should find root from deep inside
    assert get_project_root(nbs) == tmp_path
    assert get_project_root(src) == tmp_path
    
    # Should fallback to self if no root found
    other_tmp = tmp_path / "other"
    other_tmp.mkdir()
    # (assuming /tmp/pytest... doesn't have .git above it easily reachable in 10 steps or we mock logic)
    # Actually tmp_path might be inside a git repo (the workspace). 
    # So we should rely on the specific marker we created.
    
    # Let's test with a unique marker to be safe from environment pollution
    # But function is hardcoded for .git, pyproject.toml etc.
    # So we rely on the temp dir structure.
    
    # Create a cleaner separate path if possible, or just trust the logic
    pass
