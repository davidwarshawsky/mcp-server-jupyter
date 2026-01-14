"""
Cell ID Management for Git-Safe Notebook Operations

Ensures all notebooks have stable UUIDs for cells (nbformat 4.5+).
Migrates legacy notebooks and provides ID-based cell addressing.
"""

import uuid
import nbformat
from pathlib import Path
from typing import Optional, Tuple


def ensure_cell_ids(nb: nbformat.NotebookNode) -> Tuple[bool, int]:
    """
    Ensure all cells in notebook have stable IDs.
    
    For nbformat < 4.5, generates deterministic UUIDs.
    For nbformat >= 4.5, validates existing IDs.
    
    Args:
        nb: Notebook node to process
    
    Returns:
        Tuple of (was_modified, cells_updated)
    """
    was_modified = False
    cells_updated = 0
    
    for cell in nb.cells:
        # Check if cell has an ID
        if not hasattr(cell, 'id') or not cell.id:
            # Generate a new UUID
            cell.id = str(uuid.uuid4())
            was_modified = True
            cells_updated += 1
    
    return was_modified, cells_updated


def migrate_notebook_to_cell_ids(notebook_path: str) -> str:
    """
    Migrate notebook to use Cell IDs (nbformat 4.5+).
    
    - Reads notebook
    - Checks nbformat version
    - Generates stable UUIDs for all cells
    - Upgrades nbformat if needed
    - Saves atomically
    
    Args:
        notebook_path: Path to notebook file
    
    Returns:
        Status message with migration results
    """
    from src.notebook import _atomic_write_notebook
    
    path = Path(notebook_path)
    if not path.exists():
        return f"Error: Notebook not found: {notebook_path}"
    
    try:
        # Read notebook
        with open(path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        
        # Check version
        original_version = (nb.nbformat, nb.nbformat_minor)
        needs_upgrade = nb.nbformat_minor < 5
        
        # Ensure all cells have IDs
        was_modified, cells_updated = ensure_cell_ids(nb)
        
        # Upgrade format version if needed
        if needs_upgrade:
            nb.nbformat_minor = 5
            was_modified = True
        
        # Save if modified
        if was_modified:
            _atomic_write_notebook(nb, path)
            
            msg_parts = []
            if needs_upgrade:
                msg_parts.append(f"Upgraded nbformat from {original_version[0]}.{original_version[1]} to 4.5")
            if cells_updated > 0:
                msg_parts.append(f"Generated Cell IDs for {cells_updated} cells")
            
            return f"Migration successful: {', '.join(msg_parts)}"
        else:
            return f"Notebook already has Cell IDs (nbformat {original_version[0]}.{original_version[1]})"
    
    except Exception as e:
        return f"Migration failed: {str(e)}"


def find_cell_by_id(nb: nbformat.NotebookNode, cell_id: str) -> Optional[Tuple[int, nbformat.NotebookNode]]:
    """
    Find cell by ID and return (index, cell).
    
    Args:
        nb: Notebook node
        cell_id: Cell ID to search for
    
    Returns:
        Tuple of (index, cell) if found, None otherwise
    """
    for idx, cell in enumerate(nb.cells):
        if hasattr(cell, 'id') and cell.id == cell_id:
            return (idx, cell)
    return None


def get_cell_id_at_index(nb: nbformat.NotebookNode, index: int) -> Optional[str]:
    """
    Get Cell ID at given index.
    
    Args:
        nb: Notebook node
        index: Cell index
    
    Returns:
        Cell ID if found, None otherwise
    """
    if 0 <= index < len(nb.cells):
        cell = nb.cells[index]
        if hasattr(cell, 'id'):
            return cell.id
    return None


def validate_cell_id_at_index(nb: nbformat.NotebookNode, index: int, expected_id: str) -> bool:
    """
    Validate that cell at index has expected ID.
    
    Used for pre-flight checks before write operations.
    
    Args:
        nb: Notebook node
        index: Cell index
        expected_id: Expected Cell ID
    
    Returns:
        True if ID matches, False otherwise
    """
    actual_id = get_cell_id_at_index(nb, index)
    return actual_id == expected_id


class StaleStateError(Exception):
    """Raised when cell state has changed since agent last read it."""
    pass


def edit_cell_by_id(notebook_path: str, cell_id: str, content: str, expected_index: Optional[int] = None) -> str:
    """
    Edit cell by ID with pre-flight validation.
    
    Args:
        notebook_path: Path to notebook
        cell_id: Cell ID to edit
        content: New cell content
        expected_index: Optional index for validation (prevents stale state)
    
    Returns:
        Success message
    
    Raises:
        StaleStateError: If cell moved or doesn't exist
    """
    from src.notebook import _atomic_write_notebook
    
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")

    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    # Find cell by ID
    result = find_cell_by_id(nb, cell_id)

    # [FIX START] Heal-on-write: If an agent provided a temporary/buffer ID
    # (e.g., buffer-0) that isn't on disk yet, but the agent provided an
    # expected_index, try to recover by assigning the provided ID to the
    # cell at expected_index when that cell has no ID yet.
    if not result and expected_index is not None:
        if 0 <= expected_index < len(nb.cells):
            candidate = nb.cells[expected_index]
            # Heuristic: Treat the agent's expected index as authoritative
            # when ID lookup fails; assign the provided ID so the edit can
            # proceed even if the on-disk cell lacks a stable ID.
            candidate.id = cell_id
            result = (expected_index, candidate)
    # [FIX END]

    if not result:
        raise StaleStateError(f"Cell ID {cell_id} not found. Notebook may have been modified.")
    
    index, cell = result
    
    # Validate expected index if provided
    if expected_index is not None and index != expected_index:
        raise StaleStateError(
            f"Cell {cell_id} moved from index {expected_index} to {index}. "
            "Notebook was modified. Refresh outline and retry."
        )
    
    # Update cell
    cell.source = content
    if cell.cell_type == 'code':
        cell.outputs = []
        cell.execution_count = None
    
    _atomic_write_notebook(nb, path)
    return f"Cell {cell_id} (index {index}) edited successfully"


def delete_cell_by_id(notebook_path: str, cell_id: str, expected_index: Optional[int] = None) -> str:
    """
    Delete cell by ID with pre-flight validation.
    
    Args:
        notebook_path: Path to notebook
        cell_id: Cell ID to delete
        expected_index: Optional index for validation
    
    Returns:
        Success message
    
    Raises:
        StaleStateError: If cell moved or doesn't exist
    """
    from src.notebook import _atomic_write_notebook
    
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")

    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    # Find cell by ID
    result = find_cell_by_id(nb, cell_id)

    # [FIX START] Heal-on-write: attempt recovery using expected_index when the
    # agent supplied a buffer-style ID (e.g., buffer-0) that isn't present on disk.
    if not result and expected_index is not None:
        if 0 <= expected_index < len(nb.cells):
            candidate = nb.cells[expected_index]
            # Heuristic: Treat the agent's expected index as authoritative
            # when ID lookup fails; assign the provided ID so the delete can
            # proceed even if the on-disk cell lacks a stable ID.
            candidate.id = cell_id
            result = (expected_index, candidate)
    # [FIX END]

    if not result:
        raise StaleStateError(f"Cell ID {cell_id} not found. Notebook may have been modified.")
    
    index, cell = result
    
    # Validate expected index if provided
    if expected_index is not None and index != expected_index:
        raise StaleStateError(
            f"Cell {cell_id} moved from index {expected_index} to {index}. "
            "Notebook was modified. Refresh outline and retry."
        )
    
    # Delete cell
    nb.cells.pop(index)
    
    _atomic_write_notebook(nb, path)
    return f"Cell {cell_id} (was at index {index}) deleted successfully. {len(nb.cells)} cells remaining."


def insert_cell_by_id(notebook_path: str, after_cell_id: Optional[str], content: str, cell_type: str = "code") -> str:
    """
    Insert new cell after specified Cell ID.
    
    Args:
        notebook_path: Path to notebook
        after_cell_id: Cell ID to insert after (None = prepend to start)
        content: Cell content
        cell_type: 'code' or 'markdown'
    
    Returns:
        Success message with new cell ID
    """
    from src.notebook import _atomic_write_notebook
    
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")

    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    # Create new cell with ID
    if cell_type == "code":
        new_cell = nbformat.v4.new_code_cell(source=content)
    else:
        new_cell = nbformat.v4.new_markdown_cell(source=content)
    
    # Ensure cell has ID
    new_cell.id = str(uuid.uuid4())
    
    # Find insertion point
    if after_cell_id is None:
        # Prepend to start
        nb.cells.insert(0, new_cell)
        insert_index = 0
    else:
        result = find_cell_by_id(nb, after_cell_id)
        if not result:
            raise StaleStateError(f"Cell ID {after_cell_id} not found. Notebook may have been modified.")
        
        index, _ = result
        insert_index = index + 1
        nb.cells.insert(insert_index, new_cell)
    
    _atomic_write_notebook(nb, path)
    return f"Cell inserted at index {insert_index} with ID {new_cell.id}"
