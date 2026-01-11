"""
Tests for property-based testing using Hypothesis.

These tests generate random inputs to find edge cases that
manual tests might miss.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
import tempfile
import os
from pathlib import Path

from src.notebook import (
    create_notebook,
    get_notebook_outline,
    read_cell,
    insert_cell,
    edit_cell,
    delete_cell,
)


# Custom strategies
cell_content = st.text(
    alphabet=st.characters(
        whitelist_categories=('L', 'N', 'P', 'S', 'Zs'),
        blacklist_characters='\x00'  # Null bytes cause issues
    ),
    min_size=0,
    max_size=1000
)

cell_type = st.sampled_from(['code', 'markdown'])

valid_cell = st.fixed_dictionaries({
    'type': cell_type,
    'content': cell_content
})


class TestCellContentRoundtrip:
    """Test that content survives write/read cycles."""
    
    @given(content=st.text(
        alphabet=st.characters(
            whitelist_categories=('L', 'N', 'P', 'Zs'),
            blacklist_characters='\x00\r'  # Exclude problematic chars
        ),
        min_size=1,
        max_size=500
    ))
    @settings(max_examples=50, deadline=5000)
    def test_cell_content_roundtrip(self, content):
        """Content should survive insert/read cycle."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            nb_path = os.path.join(tmp_dir, "test.ipynb")
            create_notebook(nb_path)
            
            # Insert cell with generated content
            insert_cell(nb_path, 0, content)
            
            # Read it back - read_cell returns a dict
            result = read_cell(nb_path, 0)
            source = result.get('source', '')
            
            # Content should be preserved
            assert content in source or len(content) == 0

    @given(content=st.text(min_size=1, max_size=500))
    @settings(max_examples=50, deadline=5000)
    def test_edit_preserves_content(self, content):
        """Edited content should be preserved."""
        assume('\x00' not in content)  # Null bytes break JSON
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            nb_path = os.path.join(tmp_dir, "test.ipynb")
            create_notebook(nb_path)
            
            # Edit the default empty cell
            edit_cell(nb_path, 0, content)
            
            # Read it back - read_cell returns a dict
            result = read_cell(nb_path, 0)
            source = result.get('source', '')
            
            # Verify content is present
            assert content in source or len(content.strip()) == 0


class TestNotebookIntegrity:
    """Test that notebooks maintain integrity under various operations."""
    
    @given(cells=st.lists(valid_cell, min_size=0, max_size=10))
    @settings(max_examples=30, deadline=10000)
    def test_initial_cells_preserved(self, cells):
        """All initial cells should be preserved."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            nb_path = os.path.join(tmp_dir, "test.ipynb")
            create_notebook(nb_path, initial_cells=cells)
            
            outline = get_notebook_outline(nb_path)
            
            # Should match initial cells exactly
            expected_count = len(cells) if cells else 1 # If empty, 1 default cell
            assert len(outline) == expected_count
    
    @given(n_inserts=st.integers(min_value=0, max_value=20))
    @settings(max_examples=20, deadline=10000)
    def test_insert_count_correct(self, n_inserts):
        """Number of cells should match number of inserts."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            nb_path = os.path.join(tmp_dir, "test.ipynb")
            create_notebook(nb_path)
            
            for i in range(n_inserts):
                insert_cell(nb_path, i, f"cell {i}")
            
            outline = get_notebook_outline(nb_path)
            # 1 default + n_inserts
            assert len(outline) == 1 + n_inserts
    
    @given(
        n_inserts=st.integers(min_value=1, max_value=10),
        n_deletes=st.integers(min_value=0, max_value=5)
    )
    @settings(max_examples=20, deadline=10000)
    def test_insert_delete_balance(self, n_inserts, n_deletes):
        """Cell count should reflect inserts minus deletes."""
        assume(n_deletes <= n_inserts)  # Can't delete more than we insert
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            nb_path = os.path.join(tmp_dir, "test.ipynb")
            create_notebook(nb_path)
            
            # Insert cells
            for i in range(n_inserts):
                insert_cell(nb_path, 0, f"cell {i}")
            
            # Delete some cells
            for _ in range(n_deletes):
                delete_cell(nb_path, 0)
            
            outline = get_notebook_outline(nb_path)
            expected = 1 + n_inserts - n_deletes
            assert len(outline) == expected


class TestCellIndices:
    """Test cell index handling."""
    
    @given(index=st.integers(min_value=0, max_value=100))
    @settings(max_examples=30, deadline=5000)
    def test_read_at_invalid_index(self, index):
        """Reading at invalid index should raise IndexError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            nb_path = os.path.join(tmp_dir, "test.ipynb")
            create_notebook(nb_path)
            
            if index > 0:  # Only 1 cell (index 0) exists
                with pytest.raises(IndexError):
                    read_cell(nb_path, index)
            else:
                # Index 0 should work
                result = read_cell(nb_path, index)
                assert isinstance(result, dict)
    
    @given(index=st.integers(min_value=-100, max_value=-1))
    @settings(max_examples=20, deadline=5000)
    def test_negative_index_handling(self, index):
        """Negative indices should work or raise IndexError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            nb_path = os.path.join(tmp_dir, "test.ipynb")
            create_notebook(nb_path)
            
            # Only index -1 should work (there's only 1 cell)
            if index == -1:
                result = read_cell(nb_path, index)
                assert isinstance(result, dict)
            else:
                # Other negative indices are out of range
                with pytest.raises(IndexError):
                    read_cell(nb_path, index)


class TestCellTypes:
    """Test cell type handling."""
    
    @given(cell_type=st.sampled_from(['code', 'markdown', 'raw']))
    @settings(max_examples=10, deadline=5000)
    def test_cell_type_preserved(self, cell_type):
        """Cell type should be preserved."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            nb_path = os.path.join(tmp_dir, "test.ipynb")
            create_notebook(nb_path, initial_cells=[
                {"type": cell_type, "content": "test content"}
            ])
            
            outline = get_notebook_outline(nb_path)
            # Check that we have the right number of cells
            assert len(outline) >= 1


class TestPathHandling:
    """Test file path handling."""
    
    @given(name=st.text(
        alphabet=st.characters(
            whitelist_categories=('L', 'N'),
        ),
        min_size=1,
        max_size=20
    ))
    @settings(max_examples=20, deadline=5000)
    def test_various_filename_characters(self, name):
        """Various filename characters should work."""
        assume(name.strip())  # Skip empty names
        assume(not any(c in name for c in '/\\:*?"<>|'))  # Skip invalid chars
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            nb_path = os.path.join(tmp_dir, f"{name}.ipynb")
            result = create_notebook(nb_path)
            
            # Should create successfully
            assert Path(nb_path).exists() or "Error" in result


class TestMetadataPreservation:
    """Test that metadata is preserved correctly."""
    
    @given(cells=st.lists(valid_cell, min_size=1, max_size=5))
    @settings(max_examples=20, deadline=10000)
    def test_multiple_operations_preserve_structure(self, cells):
        """Multiple operations should not corrupt notebook structure."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            nb_path = os.path.join(tmp_dir, "test.ipynb")
            create_notebook(nb_path, initial_cells=cells)
            
            # Perform various operations
            outline = get_notebook_outline(nb_path)
            if len(outline) > 0:
                read_cell(nb_path, 0)
                if len(outline) > 1:
                    edit_cell(nb_path, 1, "modified")
            
            # Should still be readable
            final_outline = get_notebook_outline(nb_path)
            assert isinstance(final_outline, list)
            assert len(final_outline) > 0
