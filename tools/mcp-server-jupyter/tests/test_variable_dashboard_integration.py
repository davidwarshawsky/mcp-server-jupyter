import asyncio
import json
from pathlib import Path

import nbformat
import pytest

# Ensure src package is importable in test context
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from session import SessionManager  # type: ignore


def _build_manifest_code() -> str:
    """Return Python code that prints a compact JSON array of user variables.

    This code mirrors the server tool logic but keeps output small and avoids
    including modules/functions/types that could bloat or break JSON parsing.
    """
    return (
        "import sys, json, types\n"
        "def _is_user_var(name, val):\n"
        "    if name.startswith('_') or name in ('In','Out','get_ipython','exit','quit'):\n"
        "        return False\n"
        "    mod = getattr(val, '__module__', None)\n"
        "    if mod == 'builtins':\n"
        "        return False\n"
        "    if isinstance(val, types.ModuleType):\n"
        "        return False\n"
        "    if isinstance(val, types.FunctionType) or isinstance(val, type):\n"
        "        return False\n"
        "    return True\n"
        "def _inspect_var():\n"
        "    result = []\n"
        "    user_ns = globals()\n"
        "    for name, val in user_ns.items():\n"
        "        if not _is_user_var(name, val):\n"
        "            continue\n"
        "        try:\n"
        "            size_bytes = sys.getsizeof(val)\n"
        "            if size_bytes >= 1024 * 1024:\n"
        "                size_str = f'{size_bytes / (1024 * 1024):.1f} MB'\n"
        "            elif size_bytes >= 1024:\n"
        "                size_str = f'{size_bytes / 1024:.1f} KB'\n"
        "            else:\n"
        "                size_str = f'{size_bytes} B'\n"
        "            result.append({'name': name, 'type': type(val).__name__, 'size': size_str})\n"
        "        except Exception:\n"
        "            pass\n"
        "    return result\n"
        "print(json.dumps(_inspect_var(), separators=(',', ':')))\n"
    )


def _extract_manifest_from_sanitized(output: str) -> list[dict]:
    """Parse SessionManager.run_simple_code() sanitized output into an array.

    The server wraps outputs via utils.sanitize_outputs() as a JSON with keys
    like {"llm_summary": "...", "raw_outputs": [...]}. The llm_summary may
    contain our JSON array or additional preview text if offloaded. We try:
    1) JSON.parse(output) => wrapper; then JSON.parse(wrapper.llm_summary)
    2) fallback to regex extract of [ ... ] from llm_summary
    3) fallback to raw_outputs text/plain containing the JSON
    """
    wrapper = json.loads(output)
    # 1) Try llm_summary direct
    llm = wrapper.get('llm_summary', '')
    if isinstance(llm, str):
        try:
            arr = json.loads(llm)
            if isinstance(arr, list):
                return arr
        except Exception:
            # 2) bracket extract
            import re
            m = re.search(r"\[[\s\S]*\]", llm)
            if m:
                arr = json.loads(m.group(0))
                if isinstance(arr, list):
                    return arr

    # 3) raw_outputs fallback
    raws = wrapper.get('raw_outputs', [])
    for ro in raws:
        tp = ro.get('text') or (ro.get('data') or {}).get('text/plain')
        if isinstance(tp, str) and tp.strip().startswith('['):
            try:
                arr = json.loads(tp)
                if isinstance(arr, list):
                    return arr
            except Exception:
                continue
    return []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_variable_manifest_populates(tmp_path: Path):
    test_nb = tmp_path / "test_var_dashboard.ipynb"
    nb = nbformat.v4.new_notebook()
    nb.cells = [
        nbformat.v4.new_code_cell("x = 42"),
        nbformat.v4.new_code_cell("message = 'Hello World'"),
        nbformat.v4.new_code_cell("data = [1, 2, 3, 4, 5]"),
    ]
    nbformat.write(nb, test_nb)

    sm = SessionManager()
    try:
        await sm.start_kernel(str(test_nb))
        # Execute cells
        for i, cell in enumerate(nb.cells):
            task_id = await sm.execute_cell_async(str(test_nb), i, cell.source)
            # Wait for completion
            for _ in range(200):  # up to ~20s
                status = sm.get_execution_status(str(test_nb), task_id)
                if status.get("status") in {"completed", "error"}:
                    break
                await asyncio.sleep(0.1)

        # Collect manifest (with retry for timing issues)
        manifest_code = _build_manifest_code()
        manifest = []
        for attempt in range(3):
            output = await sm.run_simple_code(str(test_nb), manifest_code)
            if output and not output.startswith("Error"):
                try:
                    manifest = _extract_manifest_from_sanitized(output)
                    if manifest:  # Successfully extracted
                        break
                except json.JSONDecodeError:
                    pass  # Retry
            await asyncio.sleep(0.5)
        
        assert manifest, f"Failed to extract manifest after retries. Last output: {output!r}"

        names = {v.get('name') for v in manifest}
        # Some environments inject tiny variables (like is_wsl); ensure ours are present
        assert {"x", "message", "data"}.issubset(names)
    finally:
        await sm.stop_kernel(str(test_nb))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_variable_manifest_empty_kernel(tmp_path: Path):
    test_nb = tmp_path / "test_var_dashboard_empty.ipynb"
    nb = nbformat.v4.new_notebook()
    nbformat.write(nb, test_nb)

    sm = SessionManager()
    try:
        await sm.start_kernel(str(test_nb))
        manifest_code = _build_manifest_code()
        output = await sm.run_simple_code(str(test_nb), manifest_code)
        assert not output.startswith("Error"), output
        manifest = _extract_manifest_from_sanitized(output)

        # Some small environment variables may exist, but user-defined should be absent
        user_vars = [v for v in manifest if v.get('name') in {"x", "message", "data"}]
        assert user_vars == []
    finally:
        await sm.stop_kernel(str(test_nb))
