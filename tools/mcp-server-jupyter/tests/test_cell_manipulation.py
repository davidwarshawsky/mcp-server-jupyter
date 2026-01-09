"""
Tests for cell manipulation functions.
"""

import pytest
import nbformat
from src.notebook import (
    move_cell, copy_cell, merge_cells, split_cell, change_cell_type
)
from tests.test_helpers import (
    assert_notebook_valid,
    assert_notebook_has_cells,
    assert_cell_type,
    get_cell_source,
    get_cell_count
)


class TestMoveCell:
    """Tests for move_cell function."""
    
    def test_move_cell_forward(self, create_test_notebook):
        """Test moving a cell forward in the notebook."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "cell 0"},
            {"type": "code", "source": "cell 1"},
            {"type": "code", "source": "cell 2"}
        ])
        
        result = move_cell(nb_path, 0, 2)
        
        assert "moved" in result.lower()
        assert_notebook_has_cells(nb_path, 3)
        
        # Cell 0 should now be at position 2
        assert "cell 0" in get_cell_source(nb_path, 2)
        assert "cell 1" in get_cell_source(nb_path, 0)
        assert "cell 2" in get_cell_source(nb_path, 1)
    
    def test_move_cell_backward(self, create_test_notebook):
        """Test moving a cell backward in the notebook."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "cell 0"},
            {"type": "code", "source": "cell 1"},
            {"type": "code", "source": "cell 2"}
        ])
        
        result = move_cell(nb_path, 2, 0)
        
        assert "moved" in result.lower()
        assert "cell 2" in get_cell_source(nb_path, 0)
        assert "cell 0" in get_cell_source(nb_path, 1)
        assert "cell 1" in get_cell_source(nb_path, 2)
    
    def test_move_cell_negative_index(self, create_test_notebook):
        """Test moving cells using negative indices."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "cell 0"},
            {"type": "code", "source": "cell 1"},
            {"type": "code", "source": "cell 2"}
        ])
        
        # Move last cell to first position
        result = move_cell(nb_path, -1, 0)
        
        assert "moved" in result.lower()
        assert "cell 2" in get_cell_source(nb_path, 0)


class TestCopyCell:
    """Tests for copy_cell function."""
    
    def test_copy_cell_to_specific_position(self, create_test_notebook):
        """Test copying a cell to a specific position."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "cell 0"},
            {"type": "code", "source": "cell 1"}
        ])
        
        result = copy_cell(nb_path, 0, 2)
        
        assert "copied" in result.lower()
        assert_notebook_has_cells(nb_path, 3)
        
        # Original cell should still be at 0
        assert "cell 0" in get_cell_source(nb_path, 0)
        # Copy should be at position 2
        assert "cell 0" in get_cell_source(nb_path, 2)
    
    def test_copy_cell_to_end(self, create_test_notebook):
        """Test copying a cell to the end (None target)."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "cell 0"},
            {"type": "code", "source": "cell 1"}
        ])
        
        result = copy_cell(nb_path, 0, None)
        
        assert "copied" in result.lower()
        assert_notebook_has_cells(nb_path, 3)
        
        # Copy should be at the end
        assert "cell 0" in get_cell_source(nb_path, 2)
    
    def test_copy_cell_clears_outputs(self, create_test_notebook):
        """Test that copying a code cell clears its outputs."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "print('hello')"}
        ])
        
        # Manually add outputs to the original cell
        with open(nb_path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        
        nb.cells[0].outputs = [
            nbformat.v4.new_output('stream', name='stdout', text='hello\n')
        ]
        nb.cells[0].execution_count = 1
        
        with open(nb_path, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)
        
        # Copy the cell
        copy_cell(nb_path, 0, 1)
        
        # Check that copy has no outputs
        with open(nb_path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        
        assert len(nb.cells[1].outputs) == 0
        assert nb.cells[1].execution_count is None
    
    def test_copy_markdown_cell(self, create_test_notebook):
        """Test copying a markdown cell."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "markdown", "source": "# Header"}
        ])
        
        result = copy_cell(nb_path, 0, 1)
        
        assert "copied" in result.lower()
        assert_notebook_has_cells(nb_path, 2)
        assert_cell_type(nb_path, 1, 'markdown')
        assert "# Header" in get_cell_source(nb_path, 1)


class TestMergeCells:
    """Tests for merge_cells function."""
    
    def test_merge_two_code_cells(self, create_test_notebook):
        """Test merging two code cells."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"},
            {"type": "code", "source": "y = 2"}
        ])
        
        result = merge_cells(nb_path, 0, 1)
        
        assert "merged" in result.lower()
        assert_notebook_has_cells(nb_path, 1)
        
        source = get_cell_source(nb_path, 0)
        assert "x = 1" in source
        assert "y = 2" in source
    
    def test_merge_multiple_cells(self, create_test_notebook):
        """Test merging more than two cells."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "a = 1"},
            {"type": "code", "source": "b = 2"},
            {"type": "code", "source": "c = 3"},
            {"type": "code", "source": "d = 4"}
        ])
        
        result = merge_cells(nb_path, 1, 3)
        
        assert "merged" in result.lower()
        assert_notebook_has_cells(nb_path, 2)
        
        # First cell should be unchanged
        assert "a = 1" in get_cell_source(nb_path, 0)
        
        # Merged cell should contain all three original cells
        merged_source = get_cell_source(nb_path, 1)
        assert "b = 2" in merged_source
        assert "c = 3" in merged_source
        assert "d = 4" in merged_source
    
    def test_merge_markdown_cells(self, create_test_notebook):
        """Test merging markdown cells."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "markdown", "source": "# Title"},
            {"type": "markdown", "source": "Paragraph 1"},
            {"type": "markdown", "source": "Paragraph 2"}
        ])
        
        result = merge_cells(nb_path, 0, 2)
        
        assert "merged" in result.lower()
        assert_notebook_has_cells(nb_path, 1)
        
        source = get_cell_source(nb_path, 0)
        assert "# Title" in source
        assert "Paragraph 1" in source
        assert "Paragraph 2" in source
    
    def test_merge_with_custom_separator(self, create_test_notebook):
        """Test merging cells with custom separator."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"},
            {"type": "code", "source": "y = 2"}
        ])
        
        result = merge_cells(nb_path, 0, 1, separator="\n# ---\n")
        
        source = get_cell_source(nb_path, 0)
        assert "# ---" in source
    
    def test_merge_different_types_fails(self, create_test_notebook):
        """Test that merging cells of different types fails."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"},
            {"type": "markdown", "source": "# Header"}
        ])
        
        result = merge_cells(nb_path, 0, 1)
        
        assert "error" in result.lower() or "cannot" in result.lower()
    
    def test_merge_clears_outputs(self, create_test_notebook):
        """Test that merging code cells clears outputs."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "print('a')"},
            {"type": "code", "source": "print('b')"}
        ])
        
        # Add outputs
        with open(nb_path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        
        nb.cells[0].outputs = [nbformat.v4.new_output('stream', name='stdout', text='a\n')]
        nb.cells[0].execution_count = 1
        
        with open(nb_path, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)
        
        # Merge
        merge_cells(nb_path, 0, 1)
        
        # Check outputs cleared
        with open(nb_path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        
        assert len(nb.cells[0].outputs) == 0
        assert nb.cells[0].execution_count is None


class TestSplitCell:
    """Tests for split_cell function."""
    
    def test_split_cell_at_line(self, create_test_notebook):
        """Test splitting a cell at a specific line."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "line 0\nline 1\nline 2\nline 3"}
        ])
        
        result = split_cell(nb_path, 0, 2)
        
        assert "split" in result.lower()
        assert_notebook_has_cells(nb_path, 2)
        
        # First part
        source0 = get_cell_source(nb_path, 0)
        assert "line 0" in source0
        assert "line 1" in source0
        assert "line 2" not in source0
        
        # Second part
        source1 = get_cell_source(nb_path, 1)
        assert "line 2" in source1
        assert "line 3" in source1
    
    def test_split_markdown_cell(self, create_test_notebook):
        """Test splitting a markdown cell."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "markdown", "source": "# Title\n\nParagraph 1\n\nParagraph 2"}
        ])
        
        result = split_cell(nb_path, 0, 2)
        
        assert "split" in result.lower()
        assert_notebook_has_cells(nb_path, 2)
        assert_cell_type(nb_path, 0, 'markdown')
        assert_cell_type(nb_path, 1, 'markdown')
    
    def test_split_clears_outputs(self, create_test_notebook):
        """Test that splitting a code cell clears outputs."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "print('a')\nprint('b')"}
        ])
        
        # Add outputs
        with open(nb_path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        
        nb.cells[0].outputs = [nbformat.v4.new_output('stream', name='stdout', text='a\nb\n')]
        nb.cells[0].execution_count = 1
        
        with open(nb_path, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)
        
        # Split
        split_cell(nb_path, 0, 1)
        
        # Check outputs cleared in both cells
        with open(nb_path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        
        assert len(nb.cells[0].outputs) == 0
        assert nb.cells[0].execution_count is None
        assert len(nb.cells[1].outputs) == 0


class TestChangeCellType:
    """Tests for change_cell_type function."""
    
    def test_change_code_to_markdown(self, create_test_notebook):
        """Test changing code cell to markdown."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        result = change_cell_type(nb_path, 0, 'markdown')
        
        assert "changed" in result.lower()
        assert_cell_type(nb_path, 0, 'markdown')
        assert "x = 1" in get_cell_source(nb_path, 0)
    
    def test_change_markdown_to_code(self, create_test_notebook):
        """Test changing markdown cell to code."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "markdown", "source": "# Header"}
        ])
        
        result = change_cell_type(nb_path, 0, 'code')
        
        assert "changed" in result.lower()
        assert_cell_type(nb_path, 0, 'code')
        assert "# Header" in get_cell_source(nb_path, 0)
    
    def test_change_to_raw(self, create_test_notebook):
        """Test changing cell to raw type."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "test content"}
        ])
        
        result = change_cell_type(nb_path, 0, 'raw')
        
        assert "changed" in result.lower()
        assert_cell_type(nb_path, 0, 'raw')
    
    def test_change_preserves_content(self, create_test_notebook):
        """Test that changing type preserves cell content."""
        original_content = "important content\nline 2\nline 3"
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": original_content}
        ])
        
        change_cell_type(nb_path, 0, 'markdown')
        
        assert get_cell_source(nb_path, 0) == original_content
    
    def test_change_same_type(self, create_test_notebook):
        """Test changing to same type (should be no-op)."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        result = change_cell_type(nb_path, 0, 'code')
        
        assert "already" in result.lower()
        assert_cell_type(nb_path, 0, 'code')
    
    def test_change_invalid_type(self, create_test_notebook):
        """Test changing to invalid type fails."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "x = 1"}
        ])
        
        with pytest.raises(ValueError):
            change_cell_type(nb_path, 0, 'invalid_type')
    
    def test_change_with_negative_index(self, create_test_notebook):
        """Test changing cell type using negative index."""
        nb_path = create_test_notebook("test.ipynb", cells=[
            {"type": "code", "source": "cell 0"},
            {"type": "code", "source": "cell 1"}
        ])
        
        result = change_cell_type(nb_path, -1, 'markdown')
        
        assert "changed" in result.lower()
        assert_cell_type(nb_path, 1, 'markdown')
