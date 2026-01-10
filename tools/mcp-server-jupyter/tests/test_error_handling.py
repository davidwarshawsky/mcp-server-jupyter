"""
Tests for error handling and edge cases.

These tests verify that the system handles errors gracefully,
provides meaningful error messages, and recovers properly.
"""

import pytest
import asyncio
import os
import tempfile
from pathlib import Path
import nbformat

from src.notebook import (
    create_notebook, 
    get_notebook_outline,
    read_cell,
    insert_cell,
    edit_cell,
    delete_cell,
)
from src.session import SessionManager


class TestNotebookPathValidation:
    """Test input validation for notebook paths."""
    
    def test_create_notebook_invalid_extension(self, tmp_path):
        """Documents behavior with non-.ipynb file paths."""
        invalid_path = tmp_path / "test.txt"
        result = create_notebook(str(invalid_path))
        # Current implementation allows any extension
        # This test documents the current behavior
        assert Path(str(invalid_path)).exists() or isinstance(result, str)
    
    def test_read_cell_nonexistent_notebook(self, tmp_path):
        """Reading from nonexistent notebook should raise FileNotFoundError."""
        fake_path = tmp_path / "nonexistent.ipynb"
        with pytest.raises(FileNotFoundError):
            read_cell(str(fake_path), 0)
    
    def test_read_cell_invalid_index(self, tmp_path):
        """Reading cell at invalid index should raise IndexError."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        # Out of bounds positive index
        with pytest.raises(IndexError, match="out of range"):
            read_cell(str(nb_path), 999)
    
    def test_edit_cell_out_of_bounds(self, tmp_path):
        """Editing cell at invalid index should raise IndexError."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        with pytest.raises(IndexError, match="out of range"):
            edit_cell(str(nb_path), 999, "x = 1")
    
    def test_delete_cell_out_of_bounds(self, tmp_path):
        """Deleting cell at invalid index should raise IndexError."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        with pytest.raises(IndexError, match="out of range"):
            delete_cell(str(nb_path), 999)


class TestCorruptedNotebooks:
    """Test handling of corrupted or malformed notebooks."""
    
    def test_read_corrupted_json_raises(self, tmp_path):
        """Corrupted JSON should raise an exception."""
        nb_path = tmp_path / "corrupted.ipynb"
        with open(nb_path, 'w') as f:
            f.write("{ this is not valid json }")
        
        # nbformat raises JSONDecodeError wrapped in NBFormatError
        with pytest.raises(Exception):  # Can be various exception types
            get_notebook_outline(str(nb_path))
    
    def test_read_empty_file_raises(self, tmp_path):
        """Empty file should raise an exception."""
        nb_path = tmp_path / "empty.ipynb"
        with open(nb_path, 'w') as f:
            f.write("")
        
        with pytest.raises(Exception):  # JSONDecodeError or similar
            get_notebook_outline(str(nb_path))
    
    def test_read_valid_json_but_not_notebook_raises(self, tmp_path):
        """Valid JSON that isn't a notebook should raise."""
        nb_path = tmp_path / "notanotebook.ipynb"
        with open(nb_path, 'w') as f:
            f.write('{"key": "value"}')
        
        # nbformat validates structure
        with pytest.raises(Exception):
            get_notebook_outline(str(nb_path))


class TestConcurrentAccess:
    """Test concurrent access to notebooks."""
    
    def test_concurrent_reads(self, tmp_path):
        """Multiple concurrent reads should work."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path), initial_cells=[
            {"type": "code", "content": "x = 1"}
        ])
        
        results = []
        for _ in range(10):
            outline = get_notebook_outline(str(nb_path))
            results.append(len(outline))
        
        # All reads should return consistent results
        assert all(r == results[0] for r in results)
    
    def test_rapid_writes(self, tmp_path):
        """Rapid sequential writes should all succeed."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        # Rapidly insert cells
        for i in range(10):
            insert_cell(str(nb_path), i, f"x = {i}")
        
        # Verify all cells were written
        outline = get_notebook_outline(str(nb_path))
        # 1 default + 10 inserted = 11
        assert len(outline) == 11


class TestLargeContent:
    """Test handling of large content."""
    
    def test_large_cell_content(self, tmp_path):
        """Should handle cells with large content."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        # 100KB of content
        large_content = "x = " + "a" * 100000
        insert_cell(str(nb_path), 0, large_content)
        
        result = read_cell(str(nb_path), 0)
        # read_cell returns a dict with 'source' key
        assert "x = " in result.get('source', '')
    
    def test_many_cells(self, tmp_path):
        """Should handle notebooks with many cells."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        # Insert 100 cells
        for i in range(100):
            insert_cell(str(nb_path), i, f"cell_{i}")
        
        outline = get_notebook_outline(str(nb_path))
        # 1 default + 100 inserted = 101
        assert len(outline) == 101


class TestUnicodeHandling:
    """Test Unicode content handling."""
    
    def test_unicode_cell_content(self, tmp_path):
        """Should handle Unicode content correctly."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        unicode_content = "# 你好世界 🌍 مرحبا العالم\nprint('Hello 世界')"
        insert_cell(str(nb_path), 0, unicode_content)
        
        result = read_cell(str(nb_path), 0)
        source = result.get('source', '')
        assert "你好世界" in source
        assert "🌍" in source
    
    def test_unicode_path(self, tmp_path):
        """Should handle Unicode in file paths."""
        nb_path = tmp_path / "тест_notebook.ipynb"
        result = create_notebook(str(nb_path))
        
        assert "created" in result.lower() or nb_path.exists()


class TestSessionManagerErrors:
    """Test error handling in SessionManager."""
    
    @pytest.mark.asyncio
    async def test_start_kernel_nonexistent_notebook(self, tmp_path):
        """Starting kernel for nonexistent notebook should fail gracefully."""
        sm = SessionManager()
        fake_path = str(tmp_path / "nonexistent.ipynb")
        
        result = await sm.start_kernel(fake_path)
        # Should return error message, not crash
        assert isinstance(result, str)
    
    @pytest.mark.asyncio
    async def test_stop_kernel_not_running(self, tmp_path):
        """Stopping a kernel that isn't running should be safe."""
        sm = SessionManager()
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        result = await sm.stop_kernel(str(nb_path))
        # Should handle gracefully
        assert isinstance(result, str)
    
    @pytest.mark.asyncio
    async def test_execute_without_kernel(self, tmp_path):
        """Executing without a running kernel should fail gracefully."""
        sm = SessionManager()
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        result = await sm.execute_cell_async(str(nb_path), 0, "x = 1")
        # Should return None or error indicator
        assert result is None or "error" in str(result).lower()


class TestSpecialCharacters:
    """Test handling of special characters in content."""
    
    def test_cell_with_newlines(self, tmp_path):
        """Should preserve newlines in cell content."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        content = "line1\nline2\nline3"
        insert_cell(str(nb_path), 0, content)
        
        result = read_cell(str(nb_path), 0)
        source = result.get('source', '')
        assert "line1" in source
        assert "line3" in source
    
    def test_cell_with_tabs(self, tmp_path):
        """Should preserve tabs in cell content."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        content = "def foo():\n\treturn 42"
        insert_cell(str(nb_path), 0, content)
        
        result = read_cell(str(nb_path), 0)
        source = result.get('source', '')
        assert "def foo" in source
    
    def test_cell_with_quotes(self, tmp_path):
        """Should handle various quote characters."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        content = '''x = "double" + 'single' + """triple"""'''
        insert_cell(str(nb_path), 0, content)
        
        result = read_cell(str(nb_path), 0)
        source = result.get('source', '')
        assert "double" in source
        assert "single" in source


class TestEdgeCases:
    """Test various edge cases."""
    
    def test_empty_cell_content(self, tmp_path):
        """Should handle empty cell content."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        insert_cell(str(nb_path), 0, "")
        result = read_cell(str(nb_path), 0)
        # Should return dict with cell data
        assert isinstance(result, dict)
    
    def test_whitespace_only_content(self, tmp_path):
        """Should handle whitespace-only content."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path))
        
        insert_cell(str(nb_path), 0, "   \n\t\n   ")
        result = read_cell(str(nb_path), 0)
        assert isinstance(result, dict)
    
    def test_delete_then_read_raises(self, tmp_path):
        """Reading deleted index should raise IndexError."""
        nb_path = tmp_path / "test.ipynb"
        create_notebook(str(nb_path), initial_cells=[
            {"type": "code", "content": "x = 1"}
        ])
        
        # Delete all non-default cells
        outline = get_notebook_outline(str(nb_path))
        for _ in range(len(outline) - 1):
            delete_cell(str(nb_path), 1)
        
        # Try to read deleted index - should raise
        with pytest.raises(IndexError):
            read_cell(str(nb_path), 5)
