"""
Tests for the validation module.
"""

import pytest
from pathlib import Path

from src.validation import (
    ValidationError,
    validate_notebook_path,
    validate_cell_index,
    validate_cell_type,
    validate_cell_content,
    validate_initial_cells,
    validate_kernel_name,
    validate_venv_path,
    safe_result,
    safe_result_async,
)


class TestValidateNotebookPath:
    """Tests for notebook path validation."""

    def test_valid_path(self, tmp_path):
        """Valid notebook path should return Path object."""
        path = str(tmp_path / "test.ipynb")
        result = validate_notebook_path(path)
        assert isinstance(result, Path)

    def test_empty_path_raises(self):
        """Empty path should raise ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_notebook_path("")

    def test_none_path_raises(self):
        """None path should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_notebook_path(None)

    def test_wrong_extension_raises(self, tmp_path):
        """Non-.ipynb extension should raise ValidationError."""
        with pytest.raises(ValidationError, match=".ipynb extension"):
            validate_notebook_path(str(tmp_path / "test.py"))

    def test_must_exist_when_missing(self, tmp_path):
        """must_exist=True should raise if file doesn't exist."""
        with pytest.raises(ValidationError, match="not found"):
            validate_notebook_path(str(tmp_path / "missing.ipynb"), must_exist=True)

    def test_must_exist_when_present(self, tmp_path):
        """must_exist=True should pass if file exists."""
        nb_path = tmp_path / "exists.ipynb"
        nb_path.write_text("{}")
        result = validate_notebook_path(str(nb_path), must_exist=True)
        assert result == nb_path

    def test_directory_path_raises(self, tmp_path):
        """Path to directory should raise if it exists."""
        dir_path = tmp_path / "test.ipynb"
        dir_path.mkdir()
        with pytest.raises(ValidationError, match="directory"):
            validate_notebook_path(str(dir_path), must_exist=True)


class TestValidateCellIndex:
    """Tests for cell index validation."""

    def test_valid_index(self):
        """Valid index should return the index."""
        assert validate_cell_index(0, 5) == 0
        assert validate_cell_index(4, 5) == 4

    def test_negative_index(self):
        """Negative index should be normalized."""
        assert validate_cell_index(-1, 5) == 4
        assert validate_cell_index(-5, 5) == 0

    def test_negative_index_disabled(self):
        """Negative index with allow_negative=False should raise."""
        with pytest.raises(ValidationError, match="Negative indices not allowed"):
            validate_cell_index(-1, 5, allow_negative=False)

    def test_out_of_range_positive(self):
        """Out of range positive index should raise."""
        with pytest.raises(ValidationError, match="out of range"):
            validate_cell_index(10, 5)

    def test_out_of_range_negative(self):
        """Out of range negative index should raise."""
        with pytest.raises(ValidationError, match="out of range"):
            validate_cell_index(-10, 5)

    def test_empty_notebook(self):
        """Empty notebook should raise."""
        with pytest.raises(ValidationError, match="no cells"):
            validate_cell_index(0, 0)

    def test_non_integer_raises(self):
        """Non-integer index should raise."""
        with pytest.raises(ValidationError, match="must be an integer"):
            validate_cell_index("0", 5)


class TestValidateCellType:
    """Tests for cell type validation."""

    def test_valid_types(self):
        """Valid cell types should pass."""
        assert validate_cell_type("code") == "code"
        assert validate_cell_type("markdown") == "markdown"
        assert validate_cell_type("raw") == "raw"

    def test_case_insensitive(self):
        """Cell type validation should be case insensitive."""
        assert validate_cell_type("CODE") == "code"
        assert validate_cell_type("Markdown") == "markdown"

    def test_whitespace_stripped(self):
        """Whitespace should be stripped."""
        assert validate_cell_type("  code  ") == "code"

    def test_invalid_type_raises(self):
        """Invalid cell type should raise."""
        with pytest.raises(ValidationError, match="Invalid cell type"):
            validate_cell_type("python")

    def test_non_string_raises(self):
        """Non-string cell type should raise."""
        with pytest.raises(ValidationError, match="must be a string"):
            validate_cell_type(123)


class TestValidateCellContent:
    """Tests for cell content validation."""

    def test_valid_string(self):
        """Valid string content should pass."""
        assert validate_cell_content("x = 1") == "x = 1"

    def test_empty_string(self):
        """Empty string should pass."""
        assert validate_cell_content("") == ""

    def test_none_becomes_empty(self):
        """None should become empty string."""
        assert validate_cell_content(None) == ""

    def test_null_byte_raises(self):
        """Content with null bytes should raise."""
        with pytest.raises(ValidationError, match="null bytes"):
            validate_cell_content("x = 1\x00")

    def test_unicode_content(self):
        """Unicode content should pass."""
        content = "# 你好世界 🌍"
        assert validate_cell_content(content) == content

    def test_multiline_content(self):
        """Multiline content should pass."""
        content = "line1\nline2\nline3"
        assert validate_cell_content(content) == content


class TestValidateInitialCells:
    """Tests for initial cells validation."""

    def test_none_returns_empty(self):
        """None should return empty list."""
        assert validate_initial_cells(None) == []

    def test_empty_list(self):
        """Empty list should pass."""
        assert validate_initial_cells([]) == []

    def test_valid_cells(self):
        """Valid cells should pass."""
        cells = [
            {"type": "code", "content": "x = 1"},
            {"type": "markdown", "content": "# Title"},
        ]
        result = validate_initial_cells(cells)
        assert len(result) == 2
        assert result[0]["type"] == "code"
        assert result[1]["type"] == "markdown"

    def test_missing_type_defaults_to_code(self):
        """Missing type should default to code."""
        cells = [{"content": "x = 1"}]
        result = validate_initial_cells(cells)
        assert result[0]["type"] == "code"

    def test_missing_content_defaults_to_empty(self):
        """Missing content should default to empty."""
        cells = [{"type": "code"}]
        result = validate_initial_cells(cells)
        assert result[0]["content"] == ""

    def test_non_list_raises(self):
        """Non-list should raise."""
        with pytest.raises(ValidationError, match="must be a list"):
            validate_initial_cells("not a list")

    def test_non_dict_cell_raises(self):
        """Non-dict cell should raise."""
        with pytest.raises(ValidationError, match="must be a dict"):
            validate_initial_cells(["not a dict"])

    def test_invalid_cell_type_raises(self):
        """Invalid cell type in cell should raise."""
        cells = [{"type": "invalid", "content": "x = 1"}]
        with pytest.raises(ValidationError, match="Invalid cell"):
            validate_initial_cells(cells)


class TestValidateKernelName:
    """Tests for kernel name validation."""

    def test_valid_kernel_names(self):
        """Valid kernel names should pass."""
        assert validate_kernel_name("python3") == "python3"
        assert validate_kernel_name("conda-env-myenv-py") == "conda-env-myenv-py"
        assert validate_kernel_name("ir") == "ir"

    def test_empty_name_raises(self):
        """Empty kernel name should raise."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_kernel_name("")

    def test_whitespace_only_raises(self):
        """Whitespace-only name should raise."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_kernel_name("   ")

    def test_non_string_raises(self):
        """Non-string kernel name should raise."""
        with pytest.raises(ValidationError, match="must be a string"):
            validate_kernel_name(123)


class TestValidateVenvPath:
    """Tests for virtual environment path validation."""

    def test_none_returns_none(self):
        """None should return None."""
        assert validate_venv_path(None) is None

    def test_empty_returns_none(self):
        """Empty string should return None."""
        assert validate_venv_path("") is None

    def test_nonexistent_path_raises(self, tmp_path):
        """Nonexistent path should raise."""
        with pytest.raises(ValidationError, match="not found"):
            validate_venv_path(str(tmp_path / "missing"))

    def test_file_path_raises(self, tmp_path):
        """File path should raise."""
        file_path = tmp_path / "file"
        file_path.write_text("")
        with pytest.raises(ValidationError, match="not a directory"):
            validate_venv_path(str(file_path))

    def test_missing_scripts_dir_raises(self, tmp_path):
        """Directory without Scripts/bin should raise."""
        venv_path = tmp_path / "fake_venv"
        venv_path.mkdir()
        with pytest.raises(ValidationError, match="doesn't appear to be"):
            validate_venv_path(str(venv_path))

    def test_valid_venv_unix(self, tmp_path):
        """Valid Unix venv structure should pass."""
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        (venv_path / "bin").mkdir()
        result = validate_venv_path(str(venv_path))
        assert result == venv_path

    def test_valid_venv_windows(self, tmp_path):
        """Valid Windows venv structure should pass."""
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        (venv_path / "Scripts").mkdir()
        result = validate_venv_path(str(venv_path))
        assert result == venv_path


class TestSafeResultDecorator:
    """Tests for safe_result decorator."""

    def test_successful_function(self):
        """Successful function should return normally."""

        @safe_result
        def good_func():
            return "success"

        assert good_func() == "success"

    def test_validation_error(self):
        """ValidationError should be caught."""

        @safe_result
        def bad_func():
            raise ValidationError("test error")

        result = bad_func()
        assert "Error:" in result
        assert "test error" in result

    def test_file_not_found(self):
        """FileNotFoundError should be caught."""

        @safe_result
        def missing_file():
            raise FileNotFoundError("missing.txt")

        result = missing_file()
        assert "Error:" in result
        assert "not found" in result.lower()

    def test_index_error(self):
        """IndexError should be caught."""

        @safe_result
        def bad_index():
            raise IndexError("out of range")

        result = bad_index()
        assert "Error:" in result
        assert "range" in result.lower()

    def test_preserves_name(self):
        """Decorator should preserve function name."""

        @safe_result
        def named_func():
            pass

        assert named_func.__name__ == "named_func"


class TestSafeResultAsyncDecorator:
    """Tests for safe_result_async decorator."""

    @pytest.mark.asyncio
    async def test_successful_async_function(self):
        """Successful async function should return normally."""

        @safe_result_async
        async def good_async():
            return "async success"

        result = await good_async()
        assert result == "async success"

    @pytest.mark.asyncio
    async def test_validation_error_async(self):
        """ValidationError in async should be caught."""

        @safe_result_async
        async def bad_async():
            raise ValidationError("async error")

        result = await bad_async()
        assert "Error:" in result
        assert "async error" in result

    @pytest.mark.asyncio
    async def test_preserves_name_async(self):
        """Async decorator should preserve function name."""

        @safe_result_async
        async def named_async():
            pass

        assert named_async.__name__ == "named_async"
