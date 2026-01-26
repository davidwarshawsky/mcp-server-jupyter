import pytest
import asyncio
from pathlib import Path
from .harness import MCPServerHarness

# NOTE: This test relies on broadcaster notifications which are WebSocket-only.
# Stdio harness cannot receive them. Use test_starlette_testing.py or similar.
pytestmark = pytest.mark.skip(
    reason="Broadcaster notifications are WebSocket-only, not supported in Stdio harness"
)


@pytest.mark.asyncio
async def test_server_handshake_and_execution(tmp_path):
    package_root = str(Path(__file__).parent.parent)
    harness = MCPServerHarness(cwd=package_root)

    try:
        # Wrap entire test in a safety timeout (e.g. 10 seconds)
        await asyncio.wait_for(_run_test_logic(harness, tmp_path), timeout=10.0)
    finally:
        await harness.stop()


async def _run_test_logic(harness, tmp_path):
    await harness.start()
    nb_path = tmp_path / "test.ipynb"

    # 1. Create Notebook
    await harness.send_request("create_notebook", {"notebook_path": str(nb_path)})
    resp = await harness.read_response()
    assert "created" in resp["result"]["content"][0]["text"]

    # 2. Start Kernel
    await harness.send_request("start_kernel", {"notebook_path": str(nb_path)})
    resp = await harness.read_response()
    assert "Kernel started" in resp["result"]["content"][0]["text"]

    # 3. Run Code
    await harness.send_request(
        "run_cell_async",
        {
            "notebook_path": str(nb_path),
            "index": 0,
            "code_override": "print('INTEGRATION TEST')",
        },
    )
    resp = await harness.read_response()
    assert "task_id" in resp["result"]["content"][0]["text"]

    # 4. Wait for Notification
    found = False
    # Only read 5 messages max to prevent infinite loop if spamming
    for _ in range(5):
        msg = await harness.read_response()
        # Look for the output notification specifically
        if msg.get("method") == "notebook/output":
            if "INTEGRATION TEST" in str(msg["params"]["content"]):
                found = True
                break

    assert found, "Did not receive notebook/output notification"
