import asyncio
import json
from pathlib import Path

import pytest

from src import data_tools


class FakeSessionManager:
    def __init__(self, outputs):
        self._outputs = outputs

    def get_session(self, notebook_path):
        # Return a truthy object to indicate session exists
        return object()

    async def execute_cell_async(self, notebook_path, cell_index, code):
        return "exec_1"
    def get_execution_status(self, notebook_path, exec_id):
        return {"status": "completed", "outputs": self._outputs}


@pytest.mark.asyncio
async def test_query_dataframes_offloads_large_output(tmp_path):
    # Prepare a fake large output (>100KB)
    large_text = "A" * 120_000
    outputs = [{"output_type": "stream", "text": large_text}]

    fake_manager = FakeSessionManager(outputs)

    # Create a fake notebook path (directory)
    nb_dir = tmp_path / "notebooks"
    nb_dir.mkdir()
    nb_path = nb_dir / "big_output.ipynb"
    nb_path.write_text("{}")

    result_json = await data_tools.query_dataframes(fake_manager, str(nb_path), "SELECT 1")
    result = json.loads(result_json)

    # Should indicate success and contain result_asset metadata
    assert result["success"] is True
    data = result["data"]
    assert "result_asset" in data
    asset_info = data["result_asset"]

    # Check that the asset file exists on disk
    asset_path = Path(asset_info["path"])
    assert asset_path.exists()
    assert asset_path.stat().st_size >= 120_000


@pytest.mark.asyncio
async def test_query_dataframes_small_output_returns_inline(tmp_path):
    small_text = "hello\nworld"
    outputs = [{"output_type": "stream", "text": small_text}]

    fake_manager = FakeSessionManager(outputs)

    nb_dir = tmp_path / "notebooks2"
    nb_dir.mkdir()
    nb_path = nb_dir / "small_output.ipynb"
    nb_path.write_text("{}")

    result_json = await data_tools.query_dataframes(fake_manager, str(nb_path), "SELECT 1")
    result = json.loads(result_json)

    assert result["success"] is True
    data = result["data"]
    assert "result" in data
    assert data["result"] == small_text
