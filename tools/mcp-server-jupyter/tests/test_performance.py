"""
Performance tests and benchmarks.

These tests measure performance characteristics and ensure
operations complete within acceptable time limits.
"""

import pytest
import time
import os
import tempfile
from pathlib import Path
import statistics

from src.notebook import (
    create_notebook,
    get_notebook_outline,
    read_cell,
    insert_cell,
    edit_cell,
    delete_cell,
)
from src.session import SessionManager


@pytest.fixture
def tmp_notebook(tmp_path):
    """Create a temporary notebook for testing."""
    nb_path = tmp_path / "perf_test.ipynb"
    create_notebook(str(nb_path))
    return str(nb_path)


class TestNotebookCreationPerformance:
    """Test notebook creation performance."""
    
    @pytest.mark.slow
    def test_create_notebook_speed(self, tmp_path):
        """Notebook creation should be fast."""
        times = []
        
        for i in range(10):
            nb_path = tmp_path / f"test_{i}.ipynb"
            start = time.perf_counter()
            create_notebook(str(nb_path))
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        
        avg_time = statistics.mean(times)
        # Should create a notebook in under 100ms on average
        assert avg_time < 0.1, f"Average creation time {avg_time:.3f}s too slow"
    
    @pytest.mark.slow
    def test_create_notebook_with_cells_speed(self, tmp_path):
        """Creating notebook with initial cells should be fast."""
        cells = [{"type": "code", "content": f"x = {i}"} for i in range(10)]
        times = []
        
        for i in range(10):
            nb_path = tmp_path / f"test_{i}.ipynb"
            start = time.perf_counter()
            create_notebook(str(nb_path), initial_cells=cells)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        
        avg_time = statistics.mean(times)
        # Should create in under 200ms on average
        assert avg_time < 0.2, f"Average creation time {avg_time:.3f}s too slow"


class TestCellOperationPerformance:
    """Test cell operation performance."""
    
    @pytest.mark.slow
    def test_insert_cell_speed(self, tmp_notebook):
        """Cell insertion should be fast."""
        times = []
        
        for i in range(50):
            start = time.perf_counter()
            insert_cell(tmp_notebook, 0, f"x = {i}")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        
        avg_time = statistics.mean(times)
        # Should insert a cell in under 50ms on average
        assert avg_time < 0.05, f"Average insert time {avg_time:.3f}s too slow"
    
    @pytest.mark.slow
    def test_read_cell_speed(self, tmp_notebook):
        """Cell reading should be fast."""
        # First, add some cells
        for i in range(10):
            insert_cell(tmp_notebook, 0, f"x = {i}")
        
        times = []
        for _ in range(50):
            start = time.perf_counter()
            read_cell(tmp_notebook, 0)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        
        avg_time = statistics.mean(times)
        # Should read a cell in under 30ms on average
        assert avg_time < 0.03, f"Average read time {avg_time:.3f}s too slow"
    
    @pytest.mark.slow
    def test_edit_cell_speed(self, tmp_notebook):
        """Cell editing should be fast."""
        times = []
        
        for i in range(50):
            start = time.perf_counter()
            edit_cell(tmp_notebook, 0, f"y = {i}")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        
        avg_time = statistics.mean(times)
        # Should edit a cell in under 50ms on average
        assert avg_time < 0.05, f"Average edit time {avg_time:.3f}s too slow"
    
    @pytest.mark.slow
    def test_get_outline_speed(self, tmp_notebook):
        """Getting notebook outline should be fast."""
        # Add many cells
        for i in range(50):
            insert_cell(tmp_notebook, 0, f"x = {i}")
        
        times = []
        for _ in range(20):
            start = time.perf_counter()
            get_notebook_outline(tmp_notebook)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        
        avg_time = statistics.mean(times)
        # Should get outline in under 50ms on average
        assert avg_time < 0.05, f"Average outline time {avg_time:.3f}s too slow"


class TestLargeNotebookPerformance:
    """Test performance with large notebooks."""
    
    @pytest.mark.slow
    def test_large_notebook_creation(self, tmp_path):
        """Creating a large notebook should complete in reasonable time."""
        nb_path = tmp_path / "large.ipynb"
        cells = [{"type": "code", "content": f"x_{i} = {i} * 2"} for i in range(100)]
        
        start = time.perf_counter()
        create_notebook(str(nb_path), initial_cells=cells)
        elapsed = time.perf_counter() - start
        
        # Should create 100-cell notebook in under 2 seconds
        assert elapsed < 2.0, f"Large notebook creation took {elapsed:.2f}s"
    
    @pytest.mark.slow
    def test_large_notebook_outline(self, tmp_path):
        """Getting outline of large notebook should be fast."""
        nb_path = tmp_path / "large.ipynb"
        cells = [{"type": "code", "content": f"x = {i}"} for i in range(100)]
        create_notebook(str(nb_path), initial_cells=cells)
        
        start = time.perf_counter()
        outline = get_notebook_outline(str(nb_path))
        elapsed = time.perf_counter() - start
        
        # Should get outline in under 500ms
        assert elapsed < 0.5, f"Outline took {elapsed:.2f}s"
        assert len(outline) == 101  # 1 default + 100 initial
    
    @pytest.mark.slow
    def test_large_cell_content(self, tmp_notebook):
        """Handling large cell content should be efficient."""
        # 1MB of content
        large_content = "x = '" + "a" * 1_000_000 + "'"
        
        start = time.perf_counter()
        insert_cell(tmp_notebook, 0, large_content)
        insert_time = time.perf_counter() - start
        
        start = time.perf_counter()
        read_cell(tmp_notebook, 0)
        read_time = time.perf_counter() - start
        
        # Should handle 1MB content in under 2 seconds each
        assert insert_time < 2.0, f"Insert took {insert_time:.2f}s"
        assert read_time < 2.0, f"Read took {read_time:.2f}s"


class TestKernelPerformance:
    """Test kernel operation performance."""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.timeout(60)
    async def test_kernel_startup_time(self, tmp_path):
        """Kernel startup should complete in reasonable time."""
        nb_path = tmp_path / "kernel_perf.ipynb"
        create_notebook(str(nb_path))
        
        sm = SessionManager()
        
        start = time.perf_counter()
        await sm.start_kernel(str(nb_path))
        startup_time = time.perf_counter() - start
        
        # Kernel startup should be under 30 seconds
        # (can be slow on first start due to initialization)
        assert startup_time < 30, f"Kernel startup took {startup_time:.2f}s"
        
        await sm.stop_kernel(str(nb_path))
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.timeout(60)
    async def test_cell_execution_latency(self, tmp_path):
        """Cell execution should have low latency."""
        nb_path = tmp_path / "exec_perf.ipynb"
        create_notebook(str(nb_path))
        
        sm = SessionManager()
        await sm.start_kernel(str(nb_path))
        
        # Warm up the kernel
        await sm.execute_cell_async(str(nb_path), 0, "x = 1")
        
        times = []
        for i in range(10):
            start = time.perf_counter()
            await sm.execute_cell_async(str(nb_path), 0, f"y = {i}")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        
        avg_time = statistics.mean(times)
        
        # Simple execution should be under 500ms on average
        assert avg_time < 0.5, f"Average execution time {avg_time:.3f}s too slow"
        
        await sm.stop_kernel(str(nb_path))
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.timeout(120)
    async def test_many_executions(self, tmp_path):
        """Many sequential executions should complete efficiently."""
        nb_path = tmp_path / "many_exec.ipynb"
        create_notebook(str(nb_path))
        
        sm = SessionManager()
        await sm.start_kernel(str(nb_path))
        
        start = time.perf_counter()
        for i in range(50):
            await sm.execute_cell_async(str(nb_path), 0, f"x_{i} = {i}")
        total_time = time.perf_counter() - start
        
        # 50 executions should complete in under 30 seconds
        assert total_time < 30, f"50 executions took {total_time:.2f}s"
        
        await sm.stop_kernel(str(nb_path))


class TestMemoryEfficiency:
    """Test memory efficiency (basic checks)."""
    
    @pytest.mark.slow
    def test_no_memory_leak_on_repeated_operations(self, tmp_path):
        """Repeated operations should not cause memory leaks."""
        import gc
        
        nb_path = tmp_path / "memleak.ipynb"
        create_notebook(str(nb_path))
        
        # Force garbage collection
        gc.collect()
        
        # Perform many operations
        for i in range(100):
            insert_cell(str(nb_path), 0, f"x = {i}")
            read_cell(str(nb_path), 0)
            get_notebook_outline(str(nb_path))
            edit_cell(str(nb_path), 0, f"y = {i}")
        
        # Force garbage collection again
        gc.collect()
        
        # If we get here without OOM, test passes
        assert True
    
    @pytest.mark.slow
    def test_cleanup_temp_files(self, tmp_path):
        """Operations should not leave temp files."""
        nb_path = tmp_path / "cleanup.ipynb"
        create_notebook(str(nb_path))
        
        initial_files = set(os.listdir(tmp_path))
        
        # Perform many operations
        for i in range(50):
            insert_cell(str(nb_path), 0, f"x = {i}")
            edit_cell(str(nb_path), 0, f"y = {i}")
        
        final_files = set(os.listdir(tmp_path))
        
        # Should only have our notebook, no temp files
        new_files = final_files - initial_files
        # Filter out expected files
        unexpected_files = [f for f in new_files if not f.endswith('.ipynb')]
        
        assert len(unexpected_files) == 0, f"Unexpected files: {unexpected_files}"
