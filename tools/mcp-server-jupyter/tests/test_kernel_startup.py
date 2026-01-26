"""
Kernel Startup / Stabilization tests (renamed from phase1_stabilization)
"""

from pathlib import Path
import asyncio
import tempfile
import nbformat
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from session import SessionManager


async def _run_startup_tests():
    session_manager = SessionManager()
    with tempfile.NamedTemporaryFile(suffix=".ipynb", delete=False, mode="w") as f:
        nb = nbformat.v4.new_notebook()
        nbformat.write(nb, f)
        notebook_path = f.name

    try:
        await session_manager.start_kernel(notebook_path)
        await asyncio.sleep(2)

        result = await session_manager.run_simple_code(notebook_path, "_mcp_inspect")
        assert "_mcp_inspect" in result
    finally:
        await session_manager.stop_kernel(notebook_path)
        Path(notebook_path).unlink(missing_ok=True)


def test_kernel_startup_integration():
    asyncio.run(_run_startup_tests())
