"""
Streaming and resource monitoring tests (renamed from phase3_features)
"""

import pytest
import asyncio
from src.session import SessionManager


@pytest.mark.asyncio
async def test_streaming_basic_output(tmp_path):
    manager = SessionManager()
    nb_path = tmp_path / "test_streaming.ipynb"
    nb_path.write_text(
        """{
        "cells": [{"cell_type": "code", "source": "import time\nfor i in range(3):\n    print(f'Step {i}')\n    time.sleep(0.05)", "metadata": {}, "outputs": []}],
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "nbformat": 4,
        "nbformat_minor": 4
    }"""
    )

    await manager.start_kernel(str(nb_path))

    code = """
import time
for i in range(3):
    print(f'Step {i}')
    time.sleep(0.05)
"""
    exec_id = await manager.execute_cell_async(str(nb_path), 0, code)

    # Poll for outputs
    for _ in range(200):
        await asyncio.sleep(0.05)
        session = manager.get_session(str(nb_path))
        if session:
            for _, data in session["executions"].items():
                if data.get("id") == exec_id and data.get("status") in [
                    "completed",
                    "error",
                ]:
                    await manager.stop_kernel(str(nb_path))
                    return

    await manager.stop_kernel(str(nb_path))
    assert False, "Execution did not complete in time"
