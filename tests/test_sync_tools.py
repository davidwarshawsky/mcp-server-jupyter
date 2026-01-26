import json
import inspect
from pathlib import Path
import nbformat

from src.tools import sync_tools
from src import utils


def test_sync_state_default_is_minimal_append():
    src = Path(sync_tools.__file__).read_text()
    assert 'strategy: str = "minimal_append"' in src


class DummyMCP:
    def __init__(self):
        self._tools = {}

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn

        return decorator


class FakeSessionManager:
    def __init__(self, executed_indices):
        self._executed = executed_indices

    def get_session(self, notebook_path):
        return {"executed_indices": set(self._executed)}


def test_minimal_append_refuses_modified_upstream(tmp_path):
    # Create notebook with two code cells
    nb = nbformat.v4.new_notebook()
    cell0 = nbformat.v4.new_code_cell("print('changed')")
    cell1 = nbformat.v4.new_code_cell("print('new')")

    # Set an execution_hash that doesn't match to simulate modification
    cell0.metadata["mcp"] = {"execution_hash": utils.get_cell_hash("print('old')")}

    nb.cells = [cell0, cell1]

    nb_path = tmp_path / "test_nb.ipynb"
    with open(nb_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)

    dummy_mcp = DummyMCP()
    fake_mgr = FakeSessionManager([0])  # says cell 0 was previously executed

    # Register tools onto dummy mcp
    sync_tools.register_sync_tools(dummy_mcp, fake_mgr)

    # Retrieve the tool function and call it
    fn = dummy_mcp._tools.get("sync_state_from_disk")
    assert fn is not None

    # Call the coroutine (it's async) via inspect to ensure it returns the error
    import asyncio

    res_json = asyncio.get_event_loop().run_until_complete(fn(notebook_path=str(nb_path)))
    res = json.loads(res_json)

    assert res.get("error") == "upstream_modified"
    assert "modified_cells" in res
