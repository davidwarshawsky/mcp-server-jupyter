import nbformat
import os
import sys
import tempfile
import logging
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

# Configure logging
logger = logging.getLogger(__name__)

# Thread pool for blocking I/O operations
_notebook_io_pool = ThreadPoolExecutor(max_workers=2)

async def read_notebook_async(path: str):
    """
    [FIX #1] Async wrapper for nbformat.read to prevent event loop blocking.
    
    Large notebooks (>1MB) can block the asyncio loop for 100ms+,
    causing heartbeat timeouts and agent disconnects.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_notebook_io_pool, lambda: nbformat.read(path, as_version=4))


def _slice_text(text: str, line_range: Optional[List[int]] = None) -> str:
    """Helper to slice text by lines safely."""
    if not text:
        return ""
    lines = text.split('\n')
    total_lines = len(lines)
    
    if not line_range:
        return text

    start, end = line_range[0], line_range[1]
    
    # Handle negative indexing
    if start < 0: start += total_lines
    if end < 0: end += total_lines + 1 # +1 because slice is exclusive
    
    # Clamp values
    start = max(0, start)
    end = min(total_lines, end)
    
    if start >= end:
        return ""
        
    return "\n".join(lines[start:end])

def read_cell_smart(path: str, index: int, target: str = "both", fmt: str = "summary", line_range: Optional[List[int]] = None) -> str:
    """
    The Surgical Reader.
    target: "source" (code), "output" (result), or "both".
    format: "summary" (Default), "full", or "slice".
    line_range: [start_line, end_line] (e.g., [0, 10] or [-10, -1]).
    """
    try:
        nb = nbformat.read(path, as_version=4)
    except Exception as e:
        return f"Error reading notebook: {e}"
        
    if index >= len(nb.cells) or index < 0:
        return f"Error: Index {index} out of bounds (0-{len(nb.cells)-1})."
        
    cell = nb.cells[index]
    result = []
    
    # 1. Get Source
    if target in ["source", "both"]:
        src = cell.source
        if fmt == "slice" and line_range:
            src = _slice_text(src, line_range)
        # Add context header
        result.append(f"--- CELL {index} SOURCE ---")
        result.append(src)

    # 2. Get Outputs
    if target in ["output", "both"] and cell.cell_type == "code":
        raw_output = ""
        outputs = cell.get('outputs', [])
        for out in outputs:
            # Handle stream (stdout/stderr)
            if out.output_type == "stream":
                raw_output += out.text
            # Handle text/plain (execution results)
            elif "text/plain" in out.get("data", {}):
                raw_output += out.data["text/plain"]
            # Handle errors
            elif "error" == out.output_type:
                raw_output += f"\nError: {out.ename}: {out.evalue}\n"
                # traceback is usually a list of strings
                if 'traceback' in out:
                    raw_output += "\n".join(out.traceback)

        if raw_output:
            # Apply Logic
            if fmt == "summary":
                # Smart default: First 5, Last 5 lines
                lines = raw_output.split('\n')
                if len(lines) > 20: # Slightly larger buffer than 10 to make it worth truncating
                    truncated = lines[:5] + [f"\n... ({len(lines)-10} lines hidden) ...\n"] + lines[-5:]
                    raw_output = "\n".join(truncated)
                elif len(raw_output) > 2000:
                    raw_output = raw_output[:1000] + "\n... [Truncated] ...\n" + raw_output[-500:]
                    
            elif fmt == "slice" and line_range:
                raw_output = _slice_text(raw_output, line_range)
                
            elif fmt == "full":
                # Safety Cap for "Full"
                if len(raw_output) > 10000:
                    raw_output = raw_output[:10000] + "\n... [Safety Truncated by MCP Server (10k char limit)] ..."

            result.append(f"--- CELL {index} OUTPUT ---")
            result.append(raw_output)
        else:
            if target == "output":
                result.append("(No output)")

    return "\n\n".join(result)

def search_notebook(path: str, query: str, regex: bool = False) -> str:
    """
    Search for a string or regex pattern in the notebook.
    """
    try:
        nb = nbformat.read(path, as_version=4)
    except Exception as e:
        return f"Error reading notebook: {e}"

    matches = []
    
    for i, cell in enumerate(nb.cells):
        source = cell.source
        lines = source.split('\n')
        
        for line_idx, line in enumerate(lines):
            found = False
            if regex:
                if re.search(query, line):
                    found = True
            else:
                if query in line:
                    found = True
            
            if found:
                matches.append(f"Cell {i} (Line {line_idx+1}): {line.strip()}")
    
    if not matches:
        return f"No matches found for query: '{query}'"
        
    return "Matches found:\n" + "\n".join(matches)

def _atomic_write_notebook(nb: nbformat.NotebookNode, path: Path) -> None:
    """
    Write notebook atomically to prevent corruption from crashes or concurrent writes.
    
    Uses temp file + os.replace() pattern for atomic operation on all platforms.
    
    Args:
        nb: Notebook node to write
        path: Target path for the notebook file
        
    Raises:
        OSError: If write fails or path is inaccessible
    """
    # Create temp file in same directory as target (ensures same filesystem)
    temp_fd, temp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp"
    )
    
    try:
        # Write to temp file
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)
        
        # Atomic rename (replaces target if exists)
        # os.replace() is atomic on POSIX and Windows
        os.replace(temp_path, str(path))
        
    except Exception:
        # Clean up temp file on any error
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass  # Best effort cleanup
        raise


def create_notebook(
    notebook_path: str,
    kernel_name: str = "python3",
    kernel_display_name: Optional[str] = None,
    language: str = "python",
    python_version: Optional[str] = None,
    initial_cells: Optional[List[Dict[str, str]]] = None
) -> str:
    """
    Creates a new Jupyter notebook with proper metadata structure.
    
    Args:
        notebook_path: Path where the notebook will be created
        kernel_name: Name of the kernel (e.g., 'python3', 'conda-env-myenv-py')
        kernel_display_name: Display name for the kernel (defaults to kernel_name)
        language: Programming language (default: 'python')
        python_version: Python version string (e.g., '3.10.5'). Auto-detected if None.
        initial_cells: List of dicts with 'type' ('code'|'markdown') and 'content' keys
    
    Returns:
        Success message with notebook path
    """
    path = Path(notebook_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    if path.exists():
        return f"Error: Notebook already exists at {notebook_path}"
    
    # Auto-detect Python version if not provided
    if python_version is None:
        version_info = sys.version_info
        python_version = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
    
    # Set kernel display name
    if kernel_display_name is None:
        kernel_display_name = f"Python {python_version.split('.')[0]}.{python_version.split('.')[1] if len(python_version.split('.')) > 1 else '0'}"
    
    # Create notebook with proper metadata
    nb = nbformat.v4.new_notebook()

    # Create one empty code cell by default ONLY IF no initial cells provided
    # This mimics Jupyter functionality/prevents index errors, but respects initial_cells if given
    if not initial_cells:
        nb.cells.append(nbformat.v4.new_code_cell(source=""))
    
    # Set kernelspec metadata
    nb.metadata['kernelspec'] = {
        'name': kernel_name,
        'display_name': kernel_display_name,
        'language': language
    }
    
    # Set language_info metadata
    nb.metadata['language_info'] = {
        'name': language,
        'version': python_version,
        'mimetype': f'text/x-{language}',
        'file_extension': '.py',
        'pygments_lexer': 'ipython3' if language == 'python' else language,
        'codemirror_mode': {
            'name': 'ipython',
            'version': int(python_version.split('.')[0])
        } if language == 'python' else language,
        'nbconvert_exporter': 'python'
    }
    
    # Add initial cells if provided
    if initial_cells:
        for cell_spec in initial_cells:
            cell_type = cell_spec.get('type', 'code')
            content = cell_spec.get('content', '')
            
            if cell_type == 'code':
                nb.cells.append(nbformat.v4.new_code_cell(source=content))
            elif cell_type == 'markdown':
                nb.cells.append(nbformat.v4.new_markdown_cell(source=content))
            elif cell_type == 'raw':
                nb.cells.append(nbformat.v4.new_raw_cell(source=content))
    
    # Write to file atomically
    _atomic_write_notebook(nb, path)
    
    return f"Notebook created at {notebook_path} with kernel '{kernel_display_name}'"

def get_notebook_outline(notebook_path: str) -> List[Dict[str, Any]]:
    """
    Returns a low-token overview of the file with Cell IDs.
    
    Automatically migrates notebooks to nbformat 4.5+ if needed.
    Also performs provenance garbage collection.
    """
    if not os.path.exists(notebook_path):
        return []

    from src.cell_id_manager import ensure_cell_ids
    
    path = Path(notebook_path)
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    # [IIRB P0 FIX #3] Persist Cell IDs for git-safety
    # OLD BEHAVIOR: Generated IDs in-memory only, causing Heisenbug:
    # - Agent calls get_notebook_outline, gets ID "abc123"
    # - Agent tries edit_cell(id="abc123")
    # - Server restarts or user reloads
    # - ID "abc123" no longer exists (regenerated as "xyz789")
    # - Edit fails with "Cell ID not found"
    #
    # NEW BEHAVIOR: Write Cell IDs back to disk immediately
    # - Ensures stable IDs across server restarts
    # - Migrates notebooks to nbformat 4.5 for ID support
    # - Complies with git-safe cell addressing promise
    was_modified, cells_updated = ensure_cell_ids(nb)
    if was_modified:
        # Upgrade nbformat version if needed
        if nb.nbformat_minor < 5:
            nb.nbformat_minor = 5
        # Save with atomic write to persist IDs
        _atomic_write_notebook(nb, path)
        logger.info(f"Migrated {notebook_path} to nbformat 4.5 with {cells_updated} Cell IDs")

    # Build outline
    outline = []
    cell_ids = set()
    for i, cell in enumerate(nb.cells):
        source_preview = cell.source[:50] + "..." if len(cell.source) > 50 else cell.source
        state = "executed" if cell.get('outputs') or cell.get('execution_count') else "fresh"
        cell_id = getattr(cell, 'id', f"legacy-{i}")  # Fallback for safety
        cell_ids.add(cell_id)
        outline.append({
            "index": i,
            "id": cell_id,  # CRITICAL: Include Cell ID for Git-safe addressing
            "type": cell.cell_type,
            "source_preview": source_preview.replace("\n", "\\n"),
            "state": state
        })
    
    return outline

def format_outline(structure_override: List[Dict]) -> List[Dict]:
    """
    Format a structure override from VS Code into the standard outline format.
    Checks consistency and applies standard formatting.
    """
    outline = []
    for i, item in enumerate(structure_override):
        source = item.get('source', '')
        source_preview = source[:50] + "..." if len(source) > 50 else source
        
        # Infer state if not provided
        state = item.get('state', 'fresh')
        
        outline.append({
            "index": i,
            "id": item.get('id', f"buffer-{i}"),
            "type": item.get('cell_type', item.get('kind', 'code')), # VSCode uses 'kind', nbformat uses 'cell_type'
            "source_preview": source_preview.replace("\n", "\\n"),
            "state": state
        })
    return outline

def append_cell(notebook_path: str, content: str, cell_type: str = "code") -> str:
    """Adds new logic to the end. Automatically clears output."""
    path = Path(notebook_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    if not path.exists():
        nb = nbformat.v4.new_notebook()
    else:
        with open(path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)

    if cell_type == "code":
        new_cell = nbformat.v4.new_code_cell(source=content)
    else:
        new_cell = nbformat.v4.new_markdown_cell(source=content)
        
    nb.cells.append(new_cell)
    
    _atomic_write_notebook(nb, path)
    
    return f"Cell appended at index {len(nb.cells) - 1}"

def edit_cell(notebook_path: str, index: int, content: str) -> str:
    """Replaces the Code. Crucially: Automatically clears the output."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")

    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
        
    if 0 <= index < len(nb.cells):
        nb.cells[index].source = content
        if nb.cells[index].cell_type == 'code':
            nb.cells[index].outputs = []
            nb.cells[index].execution_count = None
        
        _atomic_write_notebook(nb, path)
        return f"Cell {index} edited and output cleared."
    else:
        raise IndexError(f"Cell index {index} out of range (0-{len(nb.cells)-1})")

def insert_cell(notebook_path: str, index: int, content: str, cell_type: str = "code") -> str:
    """
    Inserts cell at index. 
    Use -1 to insert *before* the last cell.
    Use append_cell to add to the very end.
    """
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
        
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    if cell_type == "code":
        new_cell = nbformat.v4.new_code_cell(source=content)
    else:
        new_cell = nbformat.v4.new_markdown_cell(source=content)
        
    # Python insert handles negative indices and out of bounds gracefully automatically
    nb.cells.insert(index, new_cell)
    
    _atomic_write_notebook(nb, path)
        
    return f"Cell inserted at index {index}."

def delete_cell(notebook_path: str, index: int) -> str:
    """Deletes a cell at a specific position. Supports -1 for last cell."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
        
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    
    # Handle negative index manually for clearer error reporting
    actual_index = index
    if index < 0:
        actual_index = total + index
        
    if 0 <= actual_index < total:
        nb.cells.pop(actual_index)
        _atomic_write_notebook(nb, path)
        return f"Cell {actual_index} (was {index}) deleted. Remaining: {len(nb.cells)}"
    else:
        raise IndexError(f"Cell index {index} out of range (Total cells: {total})")

def read_cell(notebook_path: str, index: int) -> Dict[str, Any]:
    """Reads a specific cell content and type."""
    path = Path(notebook_path)
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
        
    # Support negative indexing
    if index < 0:
        index += len(nb.cells)

    if 0 <= index < len(nb.cells):
        return dict(nb.cells[index])
    raise IndexError("Cell index out of range")

def save_cell_execution(
    notebook_path: str, 
    index: int, 
    outputs: List[Any], 
    execution_count: Optional[int] = None,
    metadata_update: Optional[Dict[str, Any]] = None
):
    """
    Updates the cell with execution results and optional provenance metadata.
    
    Args:
        notebook_path: Path to the notebook file
        index: Cell index to update
        outputs: List of output objects from kernel execution
        execution_count: Execution counter (optional)
        metadata_update: Optional metadata to inject into cell (e.g., provenance tracking)
                        Will be stored under cell.metadata['mcp_trace']
    """
    path = Path(notebook_path)
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
        
    if 0 <= index < len(nb.cells):
        # Update execution results
        nb.cells[index].outputs = outputs
        nb.cells[index].execution_count = execution_count
        
        # Inject provenance metadata if provided
        if metadata_update:
            if 'mcp' not in nb.cells[index].metadata:
                nb.cells[index].metadata['mcp'] = {}
            nb.cells[index].metadata['mcp'].update(metadata_update)
        
        _atomic_write_notebook(nb, path)

def move_cell(notebook_path: str, from_index: int, to_index: int) -> str:
    """Moves a cell from one position to another."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    
    # Handle negative indices
    if from_index < 0:
        from_index = total + from_index
    if to_index < 0:
        to_index = total + to_index
    
    if not (0 <= from_index < total):
        raise IndexError(f"Source index {from_index} out of range (0-{total-1})")
    if not (0 <= to_index < total):
        raise IndexError(f"Target index {to_index} out of range (0-{total-1})")
    
    # Move the cell
    cell = nb.cells.pop(from_index)
    nb.cells.insert(to_index, cell)
    
    _atomic_write_notebook(nb, path)
    
    return f"Cell moved from index {from_index} to {to_index}"

def copy_cell(notebook_path: str, index: int, target_index: Optional[int] = None) -> str:
    """Copies a cell to a new position. If target_index is None, appends to end."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    
    # Handle negative index for source
    if index < 0:
        index = total + index
    
    if not (0 <= index < total):
        raise IndexError(f"Source index {index} out of range (0-{total-1})")
    
    # Create a copy of the cell (dict representation)
    source_cell = nb.cells[index]
    
    # Create new cell based on type
    if source_cell.cell_type == 'code':
        new_cell = nbformat.v4.new_code_cell(source=source_cell.source)
        # Clear execution-related fields
        new_cell.outputs = []
        new_cell.execution_count = None
    elif source_cell.cell_type == 'markdown':
        new_cell = nbformat.v4.new_markdown_cell(source=source_cell.source)
    elif source_cell.cell_type == 'raw':
        new_cell = nbformat.v4.new_raw_cell(source=source_cell.source)
    else:
        new_cell = nbformat.v4.new_code_cell(source=source_cell.source)
    
    # Copy metadata if exists
    if hasattr(source_cell, 'metadata') and source_cell.metadata:
        new_cell.metadata = dict(source_cell.metadata)
    
    # Insert at target position or append
    if target_index is None:
        nb.cells.append(new_cell)
        target_index = len(nb.cells) - 1
    else:
        if target_index < 0:
            target_index = total + target_index + 1  # +1 because we're inserting after copying
        nb.cells.insert(target_index, new_cell)
    
    _atomic_write_notebook(nb, path)
    
    return f"Cell {index} copied to index {target_index}"

def merge_cells(notebook_path: str, start_index: int, end_index: int, separator: str = "\n\n") -> str:
    """Merges cells from start_index to end_index (inclusive) into a single cell."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    
    # Handle negative indices
    if start_index < 0:
        start_index = total + start_index
    if end_index < 0:
        end_index = total + end_index
    
    if not (0 <= start_index < total):
        raise IndexError(f"Start index {start_index} out of range (0-{total-1})")
    if not (0 <= end_index < total):
        raise IndexError(f"End index {end_index} out of range (0-{total-1})")
    if start_index > end_index:
        raise ValueError(f"Start index ({start_index}) must be <= end index ({end_index})")
    
    # Check if all cells are the same type
    cell_types = set(nb.cells[i].cell_type for i in range(start_index, end_index + 1))
    if len(cell_types) > 1:
        return f"Error: Cannot merge cells of different types: {cell_types}"
    
    # Merge sources
    merged_source = separator.join(
        nb.cells[i].source for i in range(start_index, end_index + 1)
    )
    
    # Update first cell with merged content
    nb.cells[start_index].source = merged_source
    
    # Clear outputs if code cell
    if nb.cells[start_index].cell_type == 'code':
        nb.cells[start_index].outputs = []
        nb.cells[start_index].execution_count = None
    
    # Remove the other cells (in reverse to maintain indices)
    for i in range(end_index, start_index, -1):
        nb.cells.pop(i)
    
    _atomic_write_notebook(nb, path)
    
    return f"Merged cells {start_index} to {end_index} into cell {start_index}"

def split_cell(notebook_path: str, index: int, split_at_line: int) -> str:
    """Splits a cell at the specified line number into two cells."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    
    # Handle negative index
    if index < 0:
        index = total + index
    
    if not (0 <= index < total):
        raise IndexError(f"Index {index} out of range (0-{total-1})")
    
    cell = nb.cells[index]
    lines = cell.source.split('\n')
    
    if not (0 < split_at_line < len(lines)):
        raise ValueError(f"Split line {split_at_line} out of range (1-{len(lines)-1})")
    
    # Split content
    first_part = '\n'.join(lines[:split_at_line])
    second_part = '\n'.join(lines[split_at_line:])
    
    # Update first cell
    cell.source = first_part
    if cell.cell_type == 'code':
        cell.outputs = []
        cell.execution_count = None
    
    # Create second cell
    if cell.cell_type == 'code':
        new_cell = nbformat.v4.new_code_cell(source=second_part)
    elif cell.cell_type == 'markdown':
        new_cell = nbformat.v4.new_markdown_cell(source=second_part)
    elif cell.cell_type == 'raw':
        new_cell = nbformat.v4.new_raw_cell(source=second_part)
    else:
        new_cell = nbformat.v4.new_code_cell(source=second_part)
    
    # Insert new cell after current
    nb.cells.insert(index + 1, new_cell)
    
    _atomic_write_notebook(nb, path)
    
    return f"Cell {index} split at line {split_at_line}. New cell created at index {index + 1}"

def change_cell_type(notebook_path: str, index: int, new_type: str) -> str:
    """Changes the type of a cell (code, markdown, or raw)."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    if new_type not in ['code', 'markdown', 'raw']:
        raise ValueError(f"Invalid cell type: {new_type}. Must be 'code', 'markdown', or 'raw'")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    
    # Handle negative index
    if index < 0:
        index = total + index
    
    if not (0 <= index < total):
        raise IndexError(f"Index {index} out of range (0-{total-1})")
    
    old_cell = nb.cells[index]
    old_type = old_cell.cell_type
    
    if old_type == new_type:
        return f"Cell {index} is already type '{new_type}'"
    
    # Create new cell with same content but different type
    source = old_cell.source
    metadata = dict(old_cell.metadata) if hasattr(old_cell, 'metadata') else {}
    
    # Create the new cell
    new_cell = None
    if new_type == 'code':
        new_cell = nbformat.v4.new_code_cell(source=source)
    elif new_type == 'markdown':
        new_cell = nbformat.v4.new_markdown_cell(source=source)
    else:  # raw
        new_cell = nbformat.v4.new_raw_cell(source=source)
    
    # Preserve metadata
    if new_cell is not None:
        new_cell.metadata = metadata
        # Replace cell
        nb.cells[index] = new_cell
    
    _atomic_write_notebook(nb, path)
    
    return f"Cell {index} type changed from '{old_type}' to '{new_type}'"

# Metadata operations
def get_notebook_metadata(notebook_path: str) -> Dict[str, Any]:
    """Gets the notebook-level metadata."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    return dict(nb.metadata)

def set_notebook_metadata(notebook_path: str, metadata: Dict[str, Any]) -> str:
    """Sets the notebook-level metadata."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    # Update metadata
    nb.metadata.update(metadata)
    
    _atomic_write_notebook(nb, path)
    
    return f"Notebook metadata updated"

def update_kernelspec(notebook_path: str, kernel_name: str, display_name: Optional[str] = None, language: Optional[str] = None) -> str:
    """Updates the kernelspec in notebook metadata."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    # Update kernelspec
    if 'kernelspec' not in nb.metadata:
        nb.metadata['kernelspec'] = {}
    
    nb.metadata['kernelspec']['name'] = kernel_name
    if display_name:
        nb.metadata['kernelspec']['display_name'] = display_name
    if language:
        nb.metadata['kernelspec']['language'] = language
    
    _atomic_write_notebook(nb, path)
    
    return f"Kernelspec updated to '{kernel_name}'"

def get_cell_metadata(notebook_path: str, index: int) -> Dict[str, Any]:
    """Gets metadata for a specific cell."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    if index < 0:
        index = total + index
    
    if not (0 <= index < total):
        raise IndexError(f"Index {index} out of range (0-{total-1})")
    
    cell = nb.cells[index]
    return dict(cell.metadata) if hasattr(cell, 'metadata') else {}

def set_cell_metadata(notebook_path: str, index: int, metadata: Dict[str, Any]) -> str:
    """Sets metadata for a specific cell."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    if index < 0:
        index = total + index
    
    if not (0 <= index < total):
        raise IndexError(f"Index {index} out of range (0-{total-1})")
    
    # Update cell metadata
    nb.cells[index].metadata.update(metadata)
    
    _atomic_write_notebook(nb, path)
    
    return f"Cell {index} metadata updated"

def add_cell_tags(notebook_path: str, index: int, tags: List[str]) -> str:
    """Adds tags to a cell's metadata."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    if index < 0:
        index = total + index
    
    if not (0 <= index < total):
        raise IndexError(f"Index {index} out of range (0-{total-1})")
    
    cell = nb.cells[index]
    
    # Ensure metadata exists
    if not hasattr(cell, 'metadata'):
        cell.metadata = {}
    
    # Get existing tags or create new list
    if 'tags' not in cell.metadata:
        cell.metadata['tags'] = []
    
    # Add new tags (avoid duplicates)
    for tag in tags:
        if tag not in cell.metadata['tags']:
            cell.metadata['tags'].append(tag)
    
    _atomic_write_notebook(nb, path)
    
    return f"Tags {tags} added to cell {index}"

def remove_cell_tags(notebook_path: str, index: int, tags: List[str]) -> str:
    """Removes tags from a cell's metadata."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    if index < 0:
        index = total + index
    
    if not (0 <= index < total):
        raise IndexError(f"Index {index} out of range (0-{total-1})")
    
    cell = nb.cells[index]
    
    # Check if tags exist
    if not hasattr(cell, 'metadata') or 'tags' not in cell.metadata:
        return f"Cell {index} has no tags"
    
    # Remove specified tags
    for tag in tags:
        if tag in cell.metadata['tags']:
            cell.metadata['tags'].remove(tag)
    
    _atomic_write_notebook(nb, path)
    
    return f"Tags {tags} removed from cell {index}"

# Output operations
def clear_cell_outputs(notebook_path: str, index: int) -> str:
    """Clears outputs from a specific cell."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    if index < 0:
        index = total + index
    
    if not (0 <= index < total):
        raise IndexError(f"Index {index} out of range (0-{total-1})")
    
    cell = nb.cells[index]
    
    if cell.cell_type == 'code':
        cell.outputs = []
        cell.execution_count = None
        
        _atomic_write_notebook(nb, path)
        
        return f"Cell {index} outputs cleared"
    else:
        return f"Cell {index} is not a code cell"

def clear_all_outputs(notebook_path: str) -> str:
    """Clears outputs from all code cells in the notebook."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    count = 0
    for cell in nb.cells:
        if cell.cell_type == 'code':
            cell.outputs = []
            cell.execution_count = None
            count += 1
    
    _atomic_write_notebook(nb, path)
    
    return f"Cleared outputs from {count} code cells"

def get_cell_outputs(notebook_path: str, index: int) -> List[Dict[str, Any]]:
    """Gets the outputs from a specific cell."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    total = len(nb.cells)
    if index < 0:
        index = total + index
    
    if not (0 <= index < total):
        raise IndexError(f"Index {index} out of range (0-{total-1})")
    
    cell = nb.cells[index]
    
    if cell.cell_type == 'code':
        return [dict(output) for output in cell.get('outputs', [])]
    else:
        return []

# Format operations
def validate_notebook(notebook_path: str) -> Dict[str, Any]:
    """Validates notebook structure and returns any issues."""
    path = Path(notebook_path)
    if not path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")
    
    issues = []
    warnings = []
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        
        # Check nbformat version
        if nb.nbformat != 4:
            warnings.append(f"Notebook format is {nb.nbformat}, expected 4")
        
        # Check for required metadata
        if 'kernelspec' not in nb.metadata:
            warnings.append("Missing kernelspec metadata")
        
        if 'language_info' not in nb.metadata:
            warnings.append("Missing language_info metadata")
        
        # Check cells
        for i, cell in enumerate(nb.cells):
            if cell.cell_type not in ['code', 'markdown', 'raw']:
                issues.append(f"Cell {i} has invalid type: {cell.cell_type}")
            
            if not hasattr(cell, 'source'):
                issues.append(f"Cell {i} missing source")
            
            if cell.cell_type == 'code':
                if not hasattr(cell, 'outputs'):
                    issues.append(f"Code cell {i} missing outputs field")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "nbformat": nb.nbformat,
            "nbformat_minor": nb.nbformat_minor,
            "cell_count": len(nb.cells)
        }
    
    except Exception as e:
        return {
            "valid": False,
            "issues": [f"Failed to parse notebook: {str(e)}"],
            "warnings": [],
            "nbformat": None,
            "nbformat_minor": None,
            "cell_count": 0
        }
