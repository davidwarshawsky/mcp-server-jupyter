import pytest
from unittest.mock import MagicMock, patch
from src.session import SessionManager


@pytest.mark.asyncio
async def test_skip_disk_write_when_client_connected(tmp_path):
    """
    Verify that _finalize_execution skips writing to .ipynb
    when a WebSocket client is connected (VS Code buffer logic).
    """
    nb_path = tmp_path / "test.ipynb"
    nb_path.write_text("{}")  # Create minimal notebook JSON

    manager = SessionManager()

    # 1. Mock ConnectionManager to simulate active client
    manager.connection_manager = MagicMock()
    manager.connection_manager.active_connections = ["mock_socket_1"]

    # 2. Mock notebook.save_cell_execution to verify it's NOT called
    with patch("src.notebook.save_cell_execution") as mock_save:
        exec_data = {"cell_index": 0, "outputs": [], "status": "completed"}

        # 3. Call internal method directly
        manager._finalize_execution(str(nb_path), exec_data)

        # 4. Assert SAVE was SKIPPED
        mock_save.assert_not_called()

    # 5. Verify it DOES save when no clients connected
    manager.connection_manager.active_connections = []
    with patch("src.notebook.save_cell_execution") as mock_save:
        manager._finalize_execution(str(nb_path), exec_data)
        mock_save.assert_called_once()
