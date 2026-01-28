
import asyncio
import os
import time
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# Import the functions/classes to be tested
from src.main import _run_startup_janitor, query_dataframes

@pytest.fixture
def assets_dir(tmp_path):
    """Create a temporary assets directory for testing."""
    assets = tmp_path / "assets"
    assets.mkdir()
    return assets

@pytest.mark.asyncio
async def test_startup_janitor_cleans_stale_files(assets_dir):
    """
    Verify that the startup janitor correctly removes files older than 24 hours
    and leaves recent files untouched.
    """
    now = time.time()
    ttl = 24 * 3600
    
    # Create a stale file that should be deleted
    stale_file = assets_dir / "stale_asset.txt"
    stale_file.touch()
    os.utime(stale_file, (now - ttl - 60, now - ttl - 60)) # Set modified time to 24h ago + 1min

    # Create a recent file that should be kept
    recent_file = assets_dir / "recent_asset.txt"
    recent_file.touch()
    os.utime(recent_file, (now - 60, now - 60)) # Set modified time to 1min ago

    # Create a file that is exactly on the edge (should be kept)
    edge_file = assets_dir / "edge_asset.txt"
    edge_file.touch()
    os.utime(edge_file, (now - ttl, now - ttl))

    # Mock Path("assets") to point to our temporary directory
    with patch('src.main.Path') as mock_path:
        mock_path.return_value = assets_dir
        
        # Run the janitor
        await _run_startup_janitor()

    # Assertions
    assert not stale_file.exists(), "Stale file should have been deleted"
    assert recent_file.exists(), "Recent file should not be deleted"
    assert edge_file.exists(), "File exactly at TTL edge should not be deleted"

@pytest.mark.asyncio
async def test_query_dataframes_graceful_failure_when_deps_missing():
    """
    Verify that `query_dataframes` (a 'superpower') returns a helpful error
    message when its optional dependencies (pandas, duckdb) are not installed,
    instead of crashing. This aligns with the "Do No Harm" principle.
    """
    # Simulate ImportError by patching the import statement
    # We patch 'pandas' as that's the first one it tries to import.
    with patch('builtins.__import__', side_effect=ImportError("No module named 'pandas'")):
        
        # The function should catch the ImportError and return a diagnostic error
        result = await query_dataframes(notebook_path="any/path", sql_query="SELECT * FROM df")

        # Assertions
        assert isinstance(result, dict)
        assert result.get("status") == "error"
        assert "This feature requires pandas and duckdb" in result.get("message", "")
        assert "pip install mcp-server-jupyter[superpowers]" in result.get("message", "")

@pytest.mark.asyncio
async def test_query_dataframes_succeeds_when_deps_present():
    """
    Verify that `query_dataframes` functions correctly when dependencies are present.
    This is a basic sanity check.
    """
    # Mock the dependencies and the session manager call
    mock_sm = MagicMock()
    mock_sm.query_dataframes.return_value = asyncio.Future()
    mock_sm.query_dataframes.return_value.set_result({"status": "success", "data": []})

    with patch('src.main.get_session_manager', return_value=mock_sm):
        # We don't need to patch imports here, as they should be installed in the test env
        try:
            import pandas
            import duckdb
        except ImportError:
            pytest.skip("Skipping superpower test: pandas or duckdb not installed in test environment.")

        result = await query_dataframes(notebook_path="any/path", sql_query="SELECT * FROM df")

        # Assertions
        assert result.get("status") == "success"
        mock_sm.query_dataframes.assert_called_once_with("any/path", "SELECT * FROM df")

