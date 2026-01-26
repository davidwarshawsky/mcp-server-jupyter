"""
Tests for notebook creation functionality.
"""

import nbformat
from src.notebook import create_notebook
from tests.test_helpers import (
    assert_notebook_valid,
    assert_notebook_has_cells,
    assert_metadata_contains,
    get_cell_count,
    get_cell_source,
)


class TestCreateNotebook:
    """Tests for create_notebook function."""

    def test_create_basic_notebook(self, tmp_notebook_dir):
        """Test creating a basic notebook with default settings."""
        nb_path = tmp_notebook_dir / "test.ipynb"

        result = create_notebook(str(nb_path))

        assert "Notebook created" in result
        assert_notebook_valid(str(nb_path))

        # Verify metadata
        assert_metadata_contains(str(nb_path), "kernelspec")
        assert_metadata_contains(str(nb_path), "language_info")

        # Should have one empty cell by default (mimics Jupyter behavior)
        assert get_cell_count(str(nb_path)) == 1

    def test_create_notebook_with_custom_kernel(self, tmp_notebook_dir):
        """Test creating notebook with custom kernel name."""
        nb_path = tmp_notebook_dir / "custom_kernel.ipynb"

        result = create_notebook(
            str(nb_path), kernel_name="mykernel", kernel_display_name="My Custom Kernel"
        )

        assert "Notebook created" in result
        assert_notebook_valid(str(nb_path))

        # Verify kernel metadata
        with open(nb_path, "r", encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)

        assert nb.metadata["kernelspec"]["name"] == "mykernel"
        assert nb.metadata["kernelspec"]["display_name"] == "My Custom Kernel"

    def test_create_notebook_with_initial_cells(self, tmp_notebook_dir):
        """Test creating notebook with initial cells."""
        nb_path = tmp_notebook_dir / "with_cells.ipynb"

        initial_cells = [
            {"type": "markdown", "content": "# Test Notebook"},
            {"type": "code", "content": "import numpy as np"},
            {"type": "code", "content": "print('hello')"},
        ]

        result = create_notebook(str(nb_path), initial_cells=initial_cells)

        assert "Notebook created" in result
        assert_notebook_valid(str(nb_path))
        # No default empty cell created when initial cells provided
        assert_notebook_has_cells(str(nb_path), 3)

        # Verify cell contents
        assert "# Test Notebook" in get_cell_source(str(nb_path), 0)
        assert "import numpy" in get_cell_source(str(nb_path), 1)
        assert "print('hello')" in get_cell_source(str(nb_path), 2)

    def test_create_notebook_with_python_version(self, tmp_notebook_dir):
        """Test creating notebook with specific Python version."""
        nb_path = tmp_notebook_dir / "versioned.ipynb"

        result = create_notebook(str(nb_path), python_version="3.10.5")

        assert "Notebook created" in result

        with open(nb_path, "r", encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)

        assert nb.metadata["language_info"]["version"] == "3.10.5"

    def test_create_notebook_auto_detects_python_version(self, tmp_notebook_dir):
        """Test that Python version is auto-detected when not provided."""
        nb_path = tmp_notebook_dir / "auto_version.ipynb"

        result = create_notebook(str(nb_path))

        assert "Notebook created" in result

        with open(nb_path, "r", encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)

        # Should have a version string
        version = nb.metadata["language_info"]["version"]
        assert version is not None
        assert len(version.split(".")) >= 2  # At least major.minor

    def test_create_notebook_already_exists(self, create_test_notebook):
        """Test creating notebook when file already exists."""
        # Create initial notebook
        nb_path = create_test_notebook("existing.ipynb")

        # Try to create again
        result = create_notebook(nb_path)

        assert "Error" in result
        assert "already exists" in result

    def test_create_notebook_creates_parent_directories(self, tmp_notebook_dir):
        """Test that parent directories are created if they don't exist."""
        nb_path = tmp_notebook_dir / "subdir1" / "subdir2" / "test.ipynb"

        result = create_notebook(str(nb_path))

        assert "Notebook created" in result
        assert nb_path.exists()
        assert_notebook_valid(str(nb_path))

    def test_create_notebook_with_mixed_cell_types(self, tmp_notebook_dir):
        """Test creating notebook with various cell types."""
        nb_path = tmp_notebook_dir / "mixed_cells.ipynb"

        initial_cells = [
            {"type": "markdown", "content": "# Header"},
            {"type": "code", "content": "x = 1"},
            {"type": "raw", "content": "Raw content"},
            {"type": "markdown", "content": "## Subheader"},
            {"type": "code", "content": "y = 2"},
        ]

        result = create_notebook(str(nb_path), initial_cells=initial_cells)

        assert "Notebook created" in result
        # No default empty cell
        assert_notebook_has_cells(str(nb_path), 5)

        with open(nb_path, "r", encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)

        # Check initial cells order
        assert nb.cells[0].cell_type == "markdown"
        assert nb.cells[0].source == "# Header"
        assert nb.cells[1].cell_type == "code"
        assert nb.cells[2].cell_type == "raw"
        assert nb.cells[3].cell_type == "markdown"
        assert nb.cells[4].cell_type == "code"

    def test_create_notebook_with_language_info(self, tmp_notebook_dir):
        """Test that language_info metadata is properly set."""
        nb_path = tmp_notebook_dir / "language_test.ipynb"

        result = create_notebook(str(nb_path), language="python")

        assert "Notebook created" in result

        with open(nb_path, "r", encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)

        lang_info = nb.metadata["language_info"]
        assert lang_info["name"] == "python"
        assert "version" in lang_info
        assert lang_info["mimetype"] == "text/x-python"
        assert lang_info["file_extension"] == ".py"
        assert "codemirror_mode" in lang_info

    def test_create_notebook_nbformat_version(self, tmp_notebook_dir):
        """Test that created notebooks use nbformat version 4."""
        nb_path = tmp_notebook_dir / "format_test.ipynb"

        create_notebook(str(nb_path))

        with open(nb_path, "r", encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)

        assert nb.nbformat == 4
        assert hasattr(nb, "nbformat_minor")


class TestCreateNotebookEdgeCases:
    """Edge case tests for notebook creation."""

    def test_create_notebook_empty_initial_cells(self, tmp_notebook_dir):
        """Test creating notebook with empty initial_cells list."""
        nb_path = tmp_notebook_dir / "empty_cells.ipynb"

        result = create_notebook(str(nb_path), initial_cells=[])

        assert "Notebook created" in result
        # Even with empty initial_cells, one default empty cell is created
        assert get_cell_count(str(nb_path)) == 1

    def test_create_notebook_cell_with_empty_content(self, tmp_notebook_dir):
        """Test creating notebook with cells that have empty content."""
        nb_path = tmp_notebook_dir / "empty_content.ipynb"

        initial_cells = [
            {"type": "code", "content": ""},
            {"type": "markdown", "content": ""},
        ]

        result = create_notebook(str(nb_path), initial_cells=initial_cells)

        assert "Notebook created" in result
        # Initial cells only
        assert_notebook_has_cells(str(nb_path), 2)

    def test_create_notebook_multiline_cells(self, tmp_notebook_dir):
        """Test creating notebook with multiline cell content."""
        nb_path = tmp_notebook_dir / "multiline.ipynb"

        initial_cells = [
            {
                "type": "code",
                "content": "def hello():\n    print('world')\n    return 42",
            },
            {"type": "markdown", "content": "# Title\n\nParagraph 1\n\nParagraph 2"},
        ]

        result = create_notebook(str(nb_path), initial_cells=initial_cells)

        assert "Notebook created" in result

        # Verify content directly
        source0 = get_cell_source(str(nb_path), 0)
        assert "def hello():" in source0
        assert "print('world')" in source0

        source1 = get_cell_source(str(nb_path), 1)
        assert "# Title" in source1
        assert "Paragraph 1" in source1
