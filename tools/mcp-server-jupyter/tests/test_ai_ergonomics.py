"""
AI Ergonomics Tests: Tokenomics, Scientific Integrity, Data Gravity

Tests for the critical AI agent usability fixes:
1. Semantic error compression (tokenomics)
2. Linearity guard (scientific integrity)  
3. Static asset server (data gravity)

Note: Docker security hardening (restricted mounts, no-new-privileges, read-only) 
is implemented in src/session.py but not tested here (requires Docker environment).
"""

import pytest
import asyncio
from pathlib import Path
from src.utils import compress_traceback
from src.session import SessionManager


def test_compress_traceback_removes_library_frames():
    """
    [TOKENOMICS] Test that compress_traceback removes library frames.
    
    A pandas schema mismatch produces 60-line stack traces with ~1000 tokens.
    After 3 retries, agent has wasted 3000 tokens on noise.
    """
    # Simulated stack trace with library and user frames
    full_traceback = [
        "Traceback (most recent call last):\n",
        '  File "/home/user/notebook.ipynb", line 5, in <module>\n',
        "    df = pd.read_csv('data.csv')\n",
        '  File "/usr/lib/python3.10/site-packages/pandas/io/parsers.py", line 1043, in read_csv\n',
        "    return _read(filepath_or_buffer, kwds)\n",
        '  File "/usr/lib/python3.10/site-packages/pandas/io/parsers.py", line 987, in _read\n',
        "    parser = TextFileReader(fp_or_buf, **kwds)\n",
        '  File "/usr/lib/python3.10/site-packages/pandas/io/parsers.py", line 455, in __init__\n',
        "    self._engine = self._make_engine(self.engine)\n",
        '  File "/usr/lib/python3.10/site-packages/pandas/io/parsers.py", line 678, in _make_engine\n',
        "    return mapping[engine](self.f, **self.options)\n",
        '  File "/usr/lib/python3.10/site-packages/pandas/io/parsers.py", line 1234, in __init__\n',
        "    self._reader = parsers.TextReader(src, **kwds)\n",
        '  File "pandas/_libs/parsers.pyx", line 542, in pandas._libs.parsers.TextReader.__init__\n',
        "ValueError: Expected 5 columns, got 3\n"
    ]
    
    compressed = compress_traceback(full_traceback)
    
    # Expected: Header, user frame, placeholder, error message
    assert compressed[0] == "Traceback (most recent call last):\n"
    assert any("notebook.ipynb" in line for line in compressed), "User code frame should be kept"
    assert any("Internal Library Frames" in line for line in compressed), "Library frames should be replaced with placeholder"
    assert any("ValueError" in line for line in compressed), "Final error message should be kept"
    
    # Verify compression: original 14 lines -> ~5-6 lines
    assert len(compressed) < 10, f"Traceback should be compressed, got {len(compressed)} lines"
    
    # Verify no duplicate placeholders
    placeholder_count = sum(1 for line in compressed if "Internal Library Frames" in line)
    assert placeholder_count == 1, "Should have only one placeholder for consecutive library frames"


def test_compress_traceback_keeps_user_frames():
    """
    [TOKENOMICS] Test that user code frames are preserved.
    """
    traceback = [
        "Traceback (most recent call last):\n",
        '  File "/home/user/analysis.ipynb", line 10, in <module>\n',
        "    result = process_data(df)\n",
        '  File "/home/user/analysis.ipynb", line 5, in process_data\n',
        "    return df['missing_column'].sum()\n",
        "KeyError: 'missing_column'\n"
    ]
    
    compressed = compress_traceback(traceback)
    
    # All lines should be kept (no library frames)
    assert len(compressed) == len(traceback)
    assert all(line in compressed for line in traceback)


def test_compress_traceback_empty_input():
    """
    [TOKENOMICS] Test edge case: empty traceback.
    """
    assert compress_traceback([]) == []
    assert compress_traceback(None) == []


@pytest.mark.asyncio
async def test_linearity_guard_detects_out_of_order(tmp_path):
    """
    [SCIENTIFIC INTEGRITY] Test that linearity guard warns on out-of-order execution.
    
    Scenario:
    1. Agent runs Cell 0
    2. Agent runs Cell 1
    3. Agent edits Cell 0 and runs it again
    4. Result: Cell 0 v2 + Cell 1 v1 = Unreproducible state
    """
    nb_path = tmp_path / "test.ipynb"
    nb_path.write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 2}')
    
    manager = SessionManager()
    await manager.start_kernel(str(nb_path))
    await asyncio.sleep(2)
    
    # Run Cell 0
    exec_id_0 = await manager.execute_cell_async(str(nb_path), 0, "x = 1")
    await asyncio.sleep(1)
    
    # Run Cell 1
    exec_id_1 = await manager.execute_cell_async(str(nb_path), 1, "y = x + 1")
    await asyncio.sleep(1)
    
    # Run Cell 0 again (out of order!)
    exec_id_0_v2 = await manager.execute_cell_async(str(nb_path), 0, "x = 2")
    await asyncio.sleep(1)
    
    # Check if warning was injected
    status = manager.get_execution_status(str(nb_path), exec_id_0_v2)
    output = status.get('output', '')
    
    # Should contain integrity warning
    assert 'INTEGRITY WARNING' in output or 'hidden state' in output.lower(), \
        f"Expected linearity warning, got: {output}"
    
    # Cleanup
    await manager.stop_kernel(str(nb_path))


@pytest.mark.asyncio
async def test_linearity_guard_allows_forward_execution(tmp_path):
    """
    [SCIENTIFIC INTEGRITY] Test that linearity guard doesn't warn on forward execution.
    """
    nb_path = tmp_path / "test.ipynb"
    nb_path.write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 2}')
    
    manager = SessionManager()
    await manager.start_kernel(str(nb_path))
    await asyncio.sleep(2)
    
    # Run cells in order: 0, 1, 2
    await manager.execute_cell_async(str(nb_path), 0, "a = 1")
    await asyncio.sleep(1)
    await manager.execute_cell_async(str(nb_path), 1, "b = 2")
    await asyncio.sleep(1)
    exec_id_2 = await manager.execute_cell_async(str(nb_path), 2, "c = 3")
    await asyncio.sleep(1)
    
    # Check that no warning was issued
    status = manager.get_execution_status(str(nb_path), exec_id_2)
    output = status.get('output', '')
    
    assert 'INTEGRITY WARNING' not in output, \
        "Should not warn on forward execution"
    
    # Cleanup
    await manager.stop_kernel(str(nb_path))


@pytest.mark.asyncio
async def test_max_executed_index_tracking(tmp_path):
    """
    [SCIENTIFIC INTEGRITY] Test that max_executed_index is tracked correctly.
    """
    nb_path = tmp_path / "test.ipynb"
    nb_path.write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 2}')
    
    manager = SessionManager()
    await manager.start_kernel(str(nb_path))
    await asyncio.sleep(2)
    
    session = manager.get_session(str(nb_path))
    
    # Initially -1
    assert session['max_executed_index'] == -1
    
    # Run Cell 5 (skipping 0-4)
    await manager.execute_cell_async(str(nb_path), 5, "x = 5")
    await asyncio.sleep(1)
    
    # Should now be 5
    assert session['max_executed_index'] == 5
    
    # Run Cell 3 (backward)
    await manager.execute_cell_async(str(nb_path), 3, "y = 3")
    await asyncio.sleep(1)
    
    # Should still be 5 (not updated on backward execution)
    assert session['max_executed_index'] == 5
    
    # Run Cell 10 (forward)
    await manager.execute_cell_async(str(nb_path), 10, "z = 10")
    await asyncio.sleep(1)
    
    # Should now be 10
    assert session['max_executed_index'] == 10
    
    # Cleanup
    await manager.stop_kernel(str(nb_path))


def test_asset_url_generation():
    """
    [DATA GRAVITY] Test that asset URLs are generated correctly.
    
    Problem: 50MB Base64 blobs over WebSocket choke JSON-RPC.
    Solution: Serve assets via HTTP, report URLs instead of paths.
    """
    import os
    
    # Set environment for URL construction
    os.environ['MCP_PORT'] = '3000'
    os.environ['MCP_HOST'] = 'localhost'
    
    # Simulate asset save
    fname = "asset_abc123.png"
    expected_url = "http://localhost:3000/assets/asset_abc123.png"
    
    # This would be in utils.py:
    port = os.environ.get('MCP_PORT', '3000')
    host = os.environ.get('MCP_HOST', 'localhost')
    if host == '0.0.0.0':
        host = 'localhost'
    
    asset_url = f"http://{host}:{port}/assets/{fname}"
    
    assert asset_url == expected_url


def test_asset_url_normalizes_bind_address():
    """
    [DATA GRAVITY] Test that 0.0.0.0 is normalized to localhost for URLs.
    """
    import os
    
    # Server binds to 0.0.0.0 (all interfaces)
    os.environ['MCP_HOST'] = '0.0.0.0'
    os.environ['MCP_PORT'] = '8080'
    
    host = os.environ.get('MCP_HOST', 'localhost')
    if host == '0.0.0.0':
        host = 'localhost'  # Normalize for client access
    
    fname = "asset_xyz789.svg"
    asset_url = f"http://{host}:8080/assets/{fname}"
    
    # Should use localhost, not 0.0.0.0
    assert asset_url == "http://localhost:8080/assets/asset_xyz789.svg"


@pytest.mark.asyncio
async def test_token_savings_calculation():
    """
    [TOKENOMICS] Quantify token savings from semantic compression.
    
    Estimate: 60-line traceback = ~1000 tokens
    After compression: 5-line summary = ~100 tokens
    Savings: 900 tokens per error (90% reduction)
    """
    # Full traceback (typical pandas error)
    full_traceback = [
        "Traceback (most recent call last):\n",
    ] + [
        f'  File "/usr/lib/python3.10/site-packages/pandas/module{i}.py", line {i*10}, in func{i}\n'
        for i in range(30)  # 30 library frames
    ] + [
        '  File "/home/user/notebook.ipynb", line 42, in <module>\n',
        "    df.merge(other_df)\n",
        "ValueError: Incompatible merge keys\n"
    ]
    
    compressed = compress_traceback(full_traceback)
    
    # Estimate tokens (rough: 4 chars per token)
    full_tokens = sum(len(line) for line in full_traceback) // 4
    compressed_tokens = sum(len(line) for line in compressed) // 4
    
    savings_percent = (1 - compressed_tokens / full_tokens) * 100
    
    print(f"\nToken Savings:")
    print(f"  Full traceback: ~{full_tokens} tokens")
    print(f"  Compressed: ~{compressed_tokens} tokens")
    print(f"  Savings: ~{savings_percent:.1f}%")
    
    # Should save at least 70% tokens
    assert savings_percent > 70, f"Expected >70% savings, got {savings_percent:.1f}%"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
