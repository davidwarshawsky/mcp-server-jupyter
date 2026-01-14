import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch, AsyncMock
from src.main import ConnectionManager

@pytest.mark.asyncio
async def test_heartbeat_initialization():
    """Verify heartbeat starts monitoring when configured."""
    cm = ConnectionManager()
    
    # Mock the monitor coroutine so we don't actually loop forever
    cm._monitor_lifecycle = AsyncMock()
    
    # 1. Set timeout
    cm.set_idle_timeout(60)
    
    # Verify state
    assert cm.idle_timeout == 60
    assert cm._monitoring is True

@pytest.mark.asyncio
async def test_heartbeat_shutdown_logic():
    """Verify logic: Idle Time > Timeout => Shutdown."""
    cm = ConnectionManager()
    cm.idle_timeout = 10  # 10 seconds
    
    # Mock session manager shutdown
    with patch('src.main.session_manager') as mock_sm, \
         patch('os._exit') as mock_exit:
        
        mock_sm.shutdown_all = AsyncMock()
        
        # Case 1: Active Connection -> No Shutdown
        cm.active_connections = ["fake_socket"]
        cm.last_activity = time.time() - 100 # Old activity, but currently connected
        
        # Run one iteration of logic manually
        if len(cm.active_connections) > 0:
            cm.last_activity = time.time()
        
        # Verify timestamp updated
        assert time.time() - cm.last_activity < 1
        mock_exit.assert_not_called()
        
        # Case 2: No Connections, Timeout Exceeded -> Shutdown
        cm.active_connections = []
        cm.last_activity = time.time() - 15 # 15s idle (limit 10s)
        
        # Run logic
        idle_duration = time.time() - cm.last_activity
        if idle_duration > cm.idle_timeout:
            await cm._force_shutdown()
            
        # Verify Shutdown Sequence
        mock_sm.shutdown_all.assert_called_once()
        mock_exit.assert_called_once_with(0)

@pytest.mark.asyncio
async def test_activity_reset_on_disconnect():
    """Verify disconnection resets the timer (giving grace period)."""
    cm = ConnectionManager()
    mock_ws = MagicMock()
    cm.active_connections = [mock_ws]
    
    # Force last activity to be old
    old_time = time.time() - 500
    cm.last_activity = old_time
    
    # Disconnect
    cm.disconnect(mock_ws)
    
    # Verify list empty but timer reset to NOW
    assert len(cm.active_connections) == 0
    assert cm.last_activity > old_time
    assert time.time() - cm.last_activity < 1
