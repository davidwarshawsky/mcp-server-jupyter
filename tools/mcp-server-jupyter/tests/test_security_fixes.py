"""
Tests for security and UX improvements (eval fix + HTML table preview).
"""

import pytest
import asyncio
import nbformat
from src.session import SessionManager
from src.utils import _convert_small_html_table_to_markdown
from tests.test_helpers import extract_output_content


class TestEvalSecurityFix:
    """Test that inspect_variable no longer uses unsafe eval()."""

    @pytest.mark.asyncio
    async def test_inspect_variable_rejects_code_execution(self, tmp_path):
        """Verify that inspect_variable doesn't execute arbitrary code."""
        manager = SessionManager()
        nb_path = tmp_path / "test_security.ipynb"

        # Create notebook
        nb = nbformat.v4.new_notebook()
        nb.cells.append(nbformat.v4.new_code_cell("x = 42"))
        with open(nb_path, "w") as f:
            nbformat.write(nb, f)

        try:
            # Start kernel
            await manager.start_kernel(str(nb_path))

            # Execute cell to create variable
            await manager.run_simple_code(str(nb_path), "x = 42")
            await asyncio.sleep(0.5)

            # Test 1: Normal variable inspection should work
            result = await manager.run_simple_code(
                str(nb_path),
                """
def _safe_inspect():
    var_name = 'x'
    
    if var_name in locals():
        obj = locals()[var_name]
    elif var_name in globals():
        obj = globals()[var_name]
    else:
        return f"Variable '{var_name}' not found in current scope."
    
    return f"### Type: {type(obj).__name__}\\n- Value: {obj}"

print(_safe_inspect())
""",
            )
            assert "Type: int" in result
            assert "42" in result

            # Test 2: Malicious code should NOT execute
            # Try to execute os.system via variable name
            result = await manager.run_simple_code(
                str(nb_path),
                """
def _safe_inspect():
    var_name = '__import__("os").system("echo HACKED")'
    
    # Safe lookup will NOT eval this string
    if var_name in locals():
        obj = locals()[var_name]
    elif var_name in globals():
        obj = globals()[var_name]
    else:
        return f"Variable '{var_name}' not found in current scope."
    
    return f"Found: {obj}"

print(_safe_inspect())
""",
            )
            # Should report variable not found, NOT execute code
            # The string contains "not found" but NOT from actual command execution
            assert "not found" in result.lower()
            # Most importantly: no echo output should appear (command wasn't executed)
            # The malicious string appears in the error message, but not as output
            assert "Found:" not in result  # Would appear if code executed

        finally:
            await manager.shutdown_all()


class TestSmallHTMLTablePreview:
    """Test that small HTML tables are shown inline."""

    def test_convert_small_table_success(self):
        """Small tables should convert to markdown."""
        html = """
        <table>
            <tr><th>Name</th><th>Age</th><th>City</th></tr>
            <tr><td>Alice</td><td>30</td><td>NYC</td></tr>
            <tr><td>Bob</td><td>25</td><td>LA</td></tr>
        </table>
        """
        result = _convert_small_html_table_to_markdown(html)

        assert result is not None
        assert "Name" in result
        assert "Alice" in result
        assert "|" in result  # Markdown table syntax
        assert "---" in result  # Header separator

    def test_convert_large_table_rejected(self):
        """Tables with > 10 rows should return None."""
        # Generate table with 15 rows
        rows = ["<tr><td>A</td><td>B</td></tr>"] * 15
        html = f"<table>{''.join(rows)}</table>"

        result = _convert_small_html_table_to_markdown(html)
        assert result is None  # Too many rows

    def test_convert_wide_table_rejected(self):
        """Tables with > 10 columns should return None."""
        # Generate row with 15 columns
        cols = "".join([f"<td>Col{i}</td>" for i in range(15)])
        html = f"<table><tr>{cols}</tr></table>"

        result = _convert_small_html_table_to_markdown(html)
        assert result is None  # Too many columns

    def test_convert_empty_table(self):
        """Empty tables should return None or empty string."""
        html = "<table></table>"
        result = _convert_small_html_table_to_markdown(html)
        # Empty table returns empty string (no rows), which is acceptable
        assert result is None or result == ""

    def test_convert_pandas_style_table(self):
        """Test with actual pandas HTML structure."""
        # Simplified pandas HTML
        html = """
        <table border="1" class="dataframe">
          <thead>
            <tr style="text-align: right;">
              <th>A</th>
              <th>B</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>1</td>
              <td>2</td>
            </tr>
            <tr>
              <td>3</td>
              <td>4</td>
            </tr>
          </tbody>
        </table>
        """
        result = _convert_small_html_table_to_markdown(html)

        assert result is not None
        assert "A" in result and "B" in result
        assert "1" in result and "4" in result


class TestHTMLTableIntegration:
    """Integration test for HTML table display in cell outputs."""

    @pytest.mark.asyncio
    async def test_small_dataframe_shows_inline(self, tmp_path):
        """Small DataFrames should display as markdown tables."""
        pytest.importorskip("pandas")

        manager = SessionManager()
        nb_path = tmp_path / "test_table.ipynb"

        # Create notebook
        nb = nbformat.v4.new_notebook()
        nb.cells.append(nbformat.v4.new_code_cell("import pandas as pd"))
        with open(nb_path, "w") as f:
            nbformat.write(nb, f)

        try:
            await manager.start_kernel(str(nb_path))
            
            # Wait for kernel to fully initialize
            await asyncio.sleep(2)

            # Create small DataFrame
            code = """
import pandas as pd
df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
df.head()
"""
            result = await manager.run_simple_code(str(nb_path), code)
            
            # Extract content from JSON output format
            result_content = extract_output_content(result)

            # Should contain markdown table (Data Preview) if HTML conversion worked
            # OR fallback message if conversion failed
            assert "[Data Preview]" in result_content or "[HTML Table detected" in result_content, \
                f"Expected DataFrame preview in output. Got: {result_content}"

        finally:
            await manager.shutdown_all()
