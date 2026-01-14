import pytest
import psutil
import os
import asyncio
from src.session import SessionManager

@pytest.mark.asyncio
async def test_file_descriptor_leak(tmp_path):
    """
    Crucible Test: Ensure creating and destroying sessions yields ZERO FD leaks.
    """
    process = psutil.Process(os.getpid())
    baseline_fds = process.num_fds()
    
    manager = SessionManager()
    nb_path = tmp_path / "leak_test.ipynb"
    nb_path.write_text('{ "cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5 }')
    
    # 1. Spin up 10 kernels sequentially
    for i in range(10):
        res = await manager.start_kernel(str(nb_path))
        # Do some minimal work (internal run)
        try:
            await manager.execute_cell_async(str(nb_path), -1, "print('work')")
        except Exception:
            pass
        await manager.stop_kernel(str(nb_path))
        # Allow event loop to settle
        await asyncio.sleep(0.1)
        import gc
        gc.collect()
    
    # 2. Force GC just in case
    import gc
    gc.collect()
    
    # 3. Check FDs
    current_fds = process.num_fds()
    diff = current_fds - baseline_fds
    
    # Allow small variance for internal python buffers, but kernel ZMQ sockets
    # (usually 5 FDs per kernel) must be gone.
    assert diff <= 2, f"Leaking File Descriptors! Baseline: {baseline_fds}, Current: {current_fds}"
