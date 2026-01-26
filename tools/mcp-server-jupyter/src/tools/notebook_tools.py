"""
Notebook Tools - Notebook-level operations.

Includes: create_notebook, get_notebook_outline, validate_notebook,
get_notebook_metadata, set_notebook_metadata, update_kernelspec,
save_notebook_clean, check_code_syntax
"""

import json
from typing import Optional, List
from src import notebook
from src.observability import get_logger

logger = get_logger(__name__)


def register_notebook_tools(mcp):
    """Register notebook-level tools with the MCP server."""

    @mcp.tool()
    def create_notebook(
        notebook_path: str,
        kernel_name: str = "python3",
        kernel_display_name: Optional[str] = None,
        language: str = "python",
        python_version: Optional[str] = None,
        initial_cells: Optional[str] = None,
    ):
        """
        Creates a new Jupyter notebook with proper metadata structure.

        Args:
            notebook_path: Path where the notebook will be created
            kernel_name: Name of the kernel (e.g., 'python3', 'conda-env-myenv-py')
            kernel_display_name: Display name for the kernel (defaults to kernel_name)
            language: Programming language (default: 'python')
            python_version: Python version string (e.g., '3.10.5'). Auto-detected if None.
            initial_cells: JSON string with list of dicts containing 'type' and 'content' keys

        Returns:
            Success message with notebook path
        """
        # Parse initial_cells if provided
        cells = None
        if initial_cells:
            try:
                cells = json.loads(initial_cells)
            except json.JSONDecodeError:
                return "Error: initial_cells must be valid JSON"

        return notebook.create_notebook(
            notebook_path,
            kernel_name,
            kernel_display_name,
            language,
            python_version,
            cells,
        )

    @mcp.tool()
    def get_notebook_outline(
        notebook_path: str, structure_override: Optional[List[dict]] = None
    ):
        """
        Explains the notebook's structure in a token-efficient manner.
        output: Cell 0 (code): `import pandas...` (12 lines). Cell 1 (markdown): "# Data Loading".
        """
        if structure_override:
            # Use the real-time buffer state from VS Code
            return notebook.format_outline(structure_override)
        else:
            # Fallback to disk (risk of stale data)
            return notebook.get_notebook_outline(notebook_path)

    @mcp.tool()
    def validate_notebook(notebook_path: str):
        """Validates notebook structure and returns any issues found."""
        result = notebook.validate_notebook(notebook_path)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def get_notebook_metadata(notebook_path: str):
        """Gets the notebook-level metadata as JSON."""
        metadata = notebook.get_notebook_metadata(notebook_path)
        return json.dumps(metadata, indent=2)

    @mcp.tool()
    def set_notebook_metadata(notebook_path: str, metadata_json: str):
        """
        Sets the notebook-level metadata.
        metadata_json: JSON string containing metadata to update
        """
        try:
            metadata = json.loads(metadata_json)
        except json.JSONDecodeError:
            return "Error: metadata_json must be valid JSON"

        return notebook.set_notebook_metadata(notebook_path, metadata)

    @mcp.tool()
    def update_kernelspec(
        notebook_path: str,
        kernel_name: str,
        display_name: Optional[str] = None,
        language: Optional[str] = None,
    ):
        """Updates the kernelspec in notebook metadata."""
        return notebook.update_kernelspec(
            notebook_path, kernel_name, display_name, language
        )

    @mcp.tool()
    def save_notebook_clean(notebook_path: str, strip_outputs: bool = False):
        """
        Saves the notebook with normalized formatting for Git.
        Optionally strips outputs for cleaner diffs.
        """
        return notebook.save_notebook_clean(notebook_path, strip_outputs)

    @mcp.tool()
    def check_code_syntax(code: str):
        """
        Validates Python syntax without executing.
        Agent Use Case: Catch SyntaxError BEFORE using run_cell to avoid polluting output.
        Returns: {'valid': True} or {'valid': False, 'error': 'line 3: unexpected indent'}
        """
        import ast

        try:
            ast.parse(code)
            return json.dumps({"valid": True, "message": "Syntax OK"})
        except SyntaxError as e:
            return json.dumps(
                {
                    "valid": False,
                    "error": f"SyntaxError at line {e.lineno}: {e.msg}",
                    "lineno": e.lineno,
                    "col": e.offset,
                    "text": e.text,
                },
                indent=2,
            )
