import nbformat
import re
from typing import List, Optional, Dict, Any, Union
from pathlib import Path

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
