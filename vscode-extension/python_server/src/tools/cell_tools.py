"""
Cell Tools - Cell manipulation tools.

Includes: append_cell, insert_cell, delete_cell, move_cell, copy_cell,
merge_cells, split_cell, change_cell_type, read_cell_smart, search_notebook,
edit_cell_by_id, delete_cell_by_id, insert_cell_by_id
"""

import json
from typing import Optional, List
from src import notebook
from src.observability import get_logger

logger = get_logger(__name__)


def register_cell_tools(mcp, session_manager):
    """Register cell manipulation tools with the MCP server."""
    
    @mcp.tool()
    def append_cell(notebook_path: str, content: str, cell_type: str = "code"):
        """
        Add new logic to the end.
        Constraint: Automatically clears output (to avoid stale data) and sets execution_count to null.
        """
        return notebook.append_cell(notebook_path, content, cell_type)

    @mcp.tool()
    def read_cell_smart(notebook_path: str, index: int, target: str = "both", fmt: str = "summary", line_range: Optional[List[int]] = None):
        """
        The Surgical Reader.
        target: "source" (code), "output" (result), or "both".
        format: "summary" (Default), "full", or "slice".
        line_range: [start_line, end_line] (e.g., [0, 10] or [-10, -1]).
        """
        if line_range and isinstance(line_range, list):
            line_range = [int(x) for x in line_range]
        return notebook.read_cell_smart(notebook_path, index, target, fmt, line_range)

    @mcp.tool()
    def insert_cell(notebook_path: str, index: int, content: str, cell_type: str = "code"):
        """Inserts a cell at a specific position."""
        return notebook.insert_cell(notebook_path, index, content, cell_type)

    @mcp.tool()
    def delete_cell(notebook_path: str, index: int):
        """Deletes a cell at a specific position."""
        return notebook.delete_cell(notebook_path, index)

    @mcp.tool()
    def search_notebook(notebook_path: str, query: str, regex: bool = False):
        """
        Don't read the file to find where df_clean is defined. Search for it.
        Returns: Found 'df_clean' in Cell 3 (Line 4) and Cell 8 (Line 1).
        """
        return notebook.search_notebook(notebook_path, query, regex)

    @mcp.tool()
    def move_cell(notebook_path: str, from_index: int, to_index: int):
        """Moves a cell from one position to another."""
        return notebook.move_cell(notebook_path, from_index, to_index)

    @mcp.tool()
    def copy_cell(notebook_path: str, index: int, target_index: Optional[int] = None):
        """Copies a cell to a new position. If target_index is None, appends to end."""
        return notebook.copy_cell(notebook_path, index, target_index)

    @mcp.tool()
    def merge_cells(notebook_path: str, start_index: int, end_index: int, separator: str = "\n\n"):
        """Merges cells from start_index to end_index (inclusive) into a single cell."""
        return notebook.merge_cells(notebook_path, start_index, end_index, separator)

    @mcp.tool()
    def split_cell(notebook_path: str, index: int, split_at_line: int):
        """Splits a cell at the specified line number into two cells."""
        return notebook.split_cell(notebook_path, index, split_at_line)

    @mcp.tool()
    def change_cell_type(notebook_path: str, index: int, new_type: str):
        """
        Changes the type of a cell (code, markdown, or raw).
        new_type must be one of: 'code', 'markdown', 'raw'
        """
        return notebook.change_cell_type(notebook_path, index, new_type)

    @mcp.tool()
    def edit_cell_by_id(notebook_path: str, cell_id: str, content: str, expected_index: Optional[int] = None):
        """
        [HANDOFF PROTOCOL] Edit a cell by its unique ID instead of index.
        
        This is safer for human-agent handoff because cell IDs are stable across
        edits and don't shift when cells are inserted/deleted.
        
        Args:
            notebook_path: Path to the notebook
            cell_id: The cell's unique ID (from get_notebook_outline)
            content: New content for the cell
            expected_index: Optional hint for faster lookup; if wrong, uses cell_id
        
        Returns:
            Success message with the actual index that was edited
        """
        return notebook.edit_cell_by_id(notebook_path, cell_id, content, expected_index)

    @mcp.tool()
    def delete_cell_by_id(notebook_path: str, cell_id: str, expected_index: Optional[int] = None):
        """
        [HANDOFF PROTOCOL] Delete a cell by its unique ID instead of index.
        
        Args:
            notebook_path: Path to the notebook
            cell_id: The cell's unique ID (from get_notebook_outline)
            expected_index: Optional hint for faster lookup; if wrong, uses cell_id
        
        Returns:
            Success message with the actual index that was deleted
        """
        return notebook.delete_cell_by_id(notebook_path, cell_id, expected_index)

    @mcp.tool()
    def insert_cell_by_id(notebook_path: str, after_cell_id: Optional[str], content: str, cell_type: str = "code"):
        """
        [HANDOFF PROTOCOL] Insert a new cell after the cell with the given ID.
        
        Args:
            notebook_path: Path to the notebook
            after_cell_id: Insert after this cell (None = insert at beginning)
            content: Content for the new cell
            cell_type: "code" or "markdown"
        
        Returns:
            Success message with the new cell's index and generated ID
        """
        return notebook.insert_cell_by_id(notebook_path, after_cell_id, content, cell_type)

    # Metadata operations for cells
    @mcp.tool()
    def get_cell_metadata(notebook_path: str, index: int):
        """Gets metadata for a specific cell as JSON."""
        metadata = notebook.get_cell_metadata(notebook_path, index)
        return json.dumps(metadata, indent=2)

    @mcp.tool()
    def set_cell_metadata(notebook_path: str, index: int, metadata_json: str):
        """
        Sets metadata for a specific cell.
        metadata_json: JSON string containing metadata to update
        """
        try:
            metadata = json.loads(metadata_json)
        except json.JSONDecodeError:
            return "Error: metadata_json must be valid JSON"
        
        return notebook.set_cell_metadata(notebook_path, index, metadata)

    @mcp.tool()
    def add_cell_tags(notebook_path: str, index: int, tags: str):
        """
        Adds tags to a cell's metadata.
        tags: JSON array of tag strings, e.g., ["important", "todo"]
        """
        try:
            tag_list = json.loads(tags)
        except json.JSONDecodeError:
            return "Error: tags must be valid JSON array"
        
        return notebook.add_cell_tags(notebook_path, index, tag_list)

    @mcp.tool()
    def remove_cell_tags(notebook_path: str, index: int, tags: str):
        """
        Removes tags from a cell's metadata.
        tags: JSON array of tag strings, e.g., ["important", "todo"]
        """
        try:
            tag_list = json.loads(tags)
        except json.JSONDecodeError:
            return "Error: tags must be valid JSON array"
        
        return notebook.remove_cell_tags(notebook_path, index, tag_list)

    # Output operations
    @mcp.tool()
    def clear_cell_outputs(notebook_path: str, index: int):
        """Clears outputs for a specific cell."""
        return notebook.clear_cell_outputs(notebook_path, index)

    @mcp.tool()
    def clear_all_outputs(notebook_path: str):
        """Clears outputs for all cells in the notebook."""
        return notebook.clear_all_outputs(notebook_path)

    @mcp.tool()
    def get_cell_outputs(notebook_path: str, index: int):
        """Gets the outputs of a specific cell as JSON."""
        outputs = notebook.get_cell_outputs(notebook_path, index)
        return json.dumps(outputs, indent=2)
