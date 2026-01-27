"""
Test helper functions for assertion and validation.
"""

import asyncio
import json
import re
import nbformat
from pathlib import Path
from typing import Dict, Any, List


def extract_output_content(output: str) -> str:
    """
    Extract meaningful content from execution output.
    
    The output may be:
    1. A JSON string with llm_summary field
    2. Plain text
    
    This function extracts the llm_summary content or returns the original
    string if it's not JSON.
    """
    if not output:
        return output
    
    try:
        data = json.loads(output)
        if isinstance(data, dict) and "llm_summary" in data:
            return data["llm_summary"]
        return output
    except (json.JSONDecodeError, TypeError):
        return output


def extract_json_from_text(text: str) -> str:
    """
    Extract JSON array or object from text that may contain preamble.
    
    The kernel may output informational messages (like SQL magic loading)
    before the actual JSON output. This function finds and extracts the
    first valid JSON array or object from the text.
    """
    if not text:
        return text
    
    # Try to find a JSON array
    array_match = re.search(r'\[[\s\S]*\]', text)
    if array_match:
        return array_match.group(0)
    
    # Try to find a JSON object  
    obj_match = re.search(r'\{[\s\S]*\}', text)
    if obj_match:
        return obj_match.group(0)
    
    return text


def assert_notebook_valid(nb_path: str) -> None:
    """
    Asserts that a notebook file exists and is valid.

    Args:
        nb_path: Path to notebook file

    Raises:
        AssertionError: If notebook is invalid
        FileNotFoundError: If notebook doesn't exist
    """
    path = Path(nb_path)
    assert path.exists(), f"Notebook does not exist: {nb_path}"

    # Try to read and parse
    with open(path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    # Basic validation
    assert hasattr(nb, "cells"), "Notebook missing cells attribute"
    assert hasattr(nb, "metadata"), "Notebook missing metadata attribute"
    assert nb.nbformat == 4, f"Expected nbformat 4, got {nb.nbformat}"


def assert_cell_equal(
    cell1: Dict[str, Any], cell2: Dict[str, Any], ignore_outputs: bool = True
) -> None:
    """
    Asserts that two cells are equal.

    Args:
        cell1: First cell dict
        cell2: Second cell dict
        ignore_outputs: If True, don't compare outputs (default: True)

    Raises:
        AssertionError: If cells are not equal
    """
    assert (
        cell1["cell_type"] == cell2["cell_type"]
    ), f"Cell types don't match: {cell1['cell_type']} != {cell2['cell_type']}"

    assert (
        cell1["source"] == cell2["source"]
    ), f"Cell sources don't match:\n{cell1['source']}\n!=\n{cell2['source']}"

    if not ignore_outputs and cell1["cell_type"] == "code":
        outputs1 = cell1.get("outputs", [])
        outputs2 = cell2.get("outputs", [])
        assert len(outputs1) == len(
            outputs2
        ), f"Output counts don't match: {len(outputs1)} != {len(outputs2)}"


def assert_output_contains(outputs: List[Dict[str, Any]], expected_text: str) -> None:
    """
    Asserts that cell outputs contain the expected text.

    Args:
        outputs: List of output dicts from a cell
        expected_text: Text that should appear in outputs

    Raises:
        AssertionError: If text not found in outputs
    """
    all_text = []

    for output in outputs:
        output_type = output.get("output_type", "")

        if output_type == "stream":
            text = output.get("text", "")
            all_text.append(text)

        elif output_type == "execute_result":
            data = output.get("data", {})
            if "text/plain" in data:
                all_text.append(data["text/plain"])

        elif output_type == "error":
            traceback = output.get("traceback", [])
            all_text.extend(traceback)

    combined_text = "\n".join(all_text)
    assert (
        expected_text in combined_text
    ), f"Expected text '{expected_text}' not found in outputs:\n{combined_text}"


async def wait_for_execution(
    session_manager,
    nb_path: str,
    exec_id: str,
    timeout: float = 10.0,
    check_interval: float = 0.5,
) -> Dict[str, Any]:
    """
    Waits for an async execution to complete.

    Args:
        session_manager: SessionManager instance
        nb_path: Path to notebook
        exec_id: Execution ID to wait for
        timeout: Maximum time to wait in seconds
        check_interval: How often to check status in seconds

    Returns:
        Final execution status dict

    Raises:
        TimeoutError: If execution doesn't complete within timeout
        AssertionError: If execution fails with error
    """
    elapsed = 0.0

    while elapsed < timeout:
        status = session_manager.get_execution_status(nb_path, exec_id)

        if status.get("status") == "completed":
            return status

        elif status.get("status") == "error":
            raise AssertionError(f"Execution failed: {status}")

        elif status.get("status") == "timeout":
            raise AssertionError(f"Execution timed out: {status}")

        await asyncio.sleep(check_interval)
        elapsed += check_interval

    raise TimeoutError(f"Execution did not complete within {timeout}s: {exec_id}")


def assert_notebook_has_cells(nb_path: str, expected_count: int) -> None:
    """
    Asserts that a notebook has the expected number of cells.

    Args:
        nb_path: Path to notebook file
        expected_count: Expected number of cells

    Raises:
        AssertionError: If cell count doesn't match
    """
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    actual_count = len(nb.cells)
    assert (
        actual_count == expected_count
    ), f"Expected {expected_count} cells, got {actual_count}"


def assert_cell_type(nb_path: str, cell_index: int, expected_type: str) -> None:
    """
    Asserts that a cell has the expected type.

    Args:
        nb_path: Path to notebook file
        cell_index: Index of cell to check
        expected_type: Expected cell type ('code', 'markdown', 'raw')

    Raises:
        AssertionError: If cell type doesn't match
    """
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    assert (
        0 <= cell_index < len(nb.cells)
    ), f"Cell index {cell_index} out of range (0-{len(nb.cells)-1})"

    actual_type = nb.cells[cell_index].cell_type
    assert (
        actual_type == expected_type
    ), f"Expected cell type '{expected_type}', got '{actual_type}'"


def assert_cell_has_tag(nb_path: str, cell_index: int, tag: str) -> None:
    """
    Asserts that a cell has a specific tag.

    Args:
        nb_path: Path to notebook file
        cell_index: Index of cell to check
        tag: Tag that should be present

    Raises:
        AssertionError: If tag not found
    """
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    assert 0 <= cell_index < len(nb.cells), f"Cell index {cell_index} out of range"

    cell = nb.cells[cell_index]
    tags = cell.metadata.get("tags", [])
    assert tag in tags, f"Tag '{tag}' not found in cell {cell_index}. Tags: {tags}"


def assert_cell_has_no_outputs(nb_path: str, cell_index: int) -> None:
    """
    Asserts that a code cell has no outputs.

    Args:
        nb_path: Path to notebook file
        cell_index: Index of cell to check

    Raises:
        AssertionError: If cell has outputs
    """
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    assert 0 <= cell_index < len(nb.cells), f"Cell index {cell_index} out of range"

    cell = nb.cells[cell_index]

    if cell.cell_type == "code":
        outputs = cell.get("outputs", [])
        assert (
            len(outputs) == 0
        ), f"Expected no outputs in cell {cell_index}, found {len(outputs)}"
    else:
        # Non-code cells don't have outputs
        pass


def assert_metadata_contains(
    nb_path: str, key: str, expected_value: Any = None
) -> None:
    """
    Asserts that notebook metadata contains a specific key.

    Args:
        nb_path: Path to notebook file
        key: Metadata key to check
        expected_value: Optional expected value for the key

    Raises:
        AssertionError: If key not found or value doesn't match
    """
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    assert (
        key in nb.metadata
    ), f"Metadata key '{key}' not found. Available keys: {list(nb.metadata.keys())}"

    if expected_value is not None:
        actual_value = nb.metadata[key]
        assert (
            actual_value == expected_value
        ), f"Metadata '{key}' value mismatch: {actual_value} != {expected_value}"


def get_cell_source(nb_path: str, cell_index: int) -> str:
    """
    Gets the source code of a cell.

    Args:
        nb_path: Path to notebook file
        cell_index: Index of cell

    Returns:
        Cell source code as string
    """
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    assert 0 <= cell_index < len(nb.cells), f"Cell index {cell_index} out of range"

    return nb.cells[cell_index].source


def get_cell_count(nb_path: str) -> int:
    """
    Gets the number of cells in a notebook.

    Args:
        nb_path: Path to notebook file

    Returns:
        Number of cells
    """
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    return len(nb.cells)
