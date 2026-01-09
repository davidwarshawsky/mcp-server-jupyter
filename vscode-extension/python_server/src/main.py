from mcp.server.fastmcp import FastMCP
import asyncio
from pathlib import Path
from typing import List, Optional
import nbformat
import json
import sys
import logging
from src.session import SessionManager
from src import notebook, utils, notebook_ops, environment

# Configure logging to stderr to avoid corrupting JSON-RPC stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

mcp = FastMCP("jupyter")
session_manager = SessionManager()

@mcp.tool()
async def start_kernel(notebook_path: str, venv_path: str = ""):
    """
    Boot a background process.
    Windows Logic: Looks for venv_path/Scripts/python.exe.
    Ubuntu Logic: Looks for venv_path/bin/python.
    Output: "Kernel started (PID: 1234). Ready for execution."
    """
    return await session_manager.start_kernel(notebook_path, venv_path if venv_path else None)

@mcp.tool()
async def stop_kernel(notebook_path: str):
    """
    Kill the process to free RAM.
    Output: "Kernel shutdown."
    """
    return await session_manager.stop_kernel(notebook_path)

@mcp.tool()
def list_kernels():
    """
    List all active kernel sessions.
    Returns: JSON with notebook paths and kernel status.
    """
    result = []
    for nb_path, session in session_manager.sessions.items():
        pid = "unknown"
        if hasattr(session.get('km'), 'kernel') and session['km'].kernel:
            pid = getattr(session['km'].kernel, 'pid', 'unknown')
        
        result.append({
            'notebook_path': nb_path,
            'pid': pid,
            'cwd': session.get('cwd', 'unknown'),
            'execution_count': session.get('execution_counter', 0),
            'queue_size': session['execution_queue'].qsize() if 'execution_queue' in session else 0,
            'stop_on_error': session.get('stop_on_error', False)
        })
    
    return json.dumps(result, indent=2)

@mcp.tool()
def detect_sync_needed(notebook_path: str):
    """
    [HANDOFF PROTOCOL] Detect if kernel state is out of sync with disk.
    
    **Purpose**: Before the agent starts work, check if a human has modified the notebook
    since the last agent execution. This prevents "KeyError" or "NameError" crashes when
    the agent assumes variables exist that were never executed in the current kernel.
    
    **How It Works**:
    1. Reads notebook metadata for last agent execution timestamp
    2. Compares with file modification time
    3. Counts cells without mcp_trace metadata (= human-added cells)
    4. Checks if kernel execution_count matches disk cell execution_counts
    
    Returns:
        JSON with:
        - sync_needed: boolean (true if sync recommended)
        - reason: Why sync is needed (if applicable)
        - human_cells: List of cell indices without agent metadata
        - last_agent_execution: Timestamp of last agent activity
        - disk_modified: File modification timestamp
        - recommendation: Action to take ("sync_state_from_disk" or "proceed")
    
    Agent Workflow:
        status = detect_sync_needed(path)
        if status['sync_needed']:
            print(f"Sync required: {status['reason']}")
            sync_state_from_disk(path, strategy="smart")
        else:
            print("State is synced. Proceeding with work.")
    """
    import os
    from pathlib import Path
    
    abs_path = str(Path(notebook_path).resolve())
    session = session_manager.get_session(notebook_path)
    
    if not session:
        return json.dumps({
            "sync_needed": True,
            "reason": "no_active_kernel",
            "recommendation": "Call start_kernel() first"
        })
    
    # Read notebook from disk
    try:
        nb = nbformat.read(notebook_path, as_version=4)
        file_stat = os.stat(notebook_path)
        disk_modified = file_stat.st_mtime
    except Exception as e:
        return json.dumps({
            "error": f"Failed to read notebook: {e}"
        })
    
    # Check for human-added cells (no mcp_trace)
    human_cells = []
    last_agent_time = None
    
    for idx, cell in enumerate(nb.cells):
        if cell.cell_type == 'code':
            metadata = cell.metadata.get('mcp_trace', {})
            if not metadata:
                human_cells.append(idx)
            else:
                # Track most recent agent execution
                exec_time = metadata.get('execution_timestamp', '')
                if exec_time and (not last_agent_time or exec_time > last_agent_time):
                    last_agent_time = exec_time
    
    # Determine if sync is needed
    sync_needed = False
    reason = None
    
    if len(human_cells) > 0:
        sync_needed = True
        reason = f"Found {len(human_cells)} cells without agent metadata (likely human-added)"
    
    # Check if file was modified after kernel start
    kernel_start_time = session.get('env_info', {}).get('start_time', '')
    if kernel_start_time:
        from datetime import datetime
        try:
            kernel_dt = datetime.fromisoformat(kernel_start_time)
            disk_dt = datetime.fromtimestamp(disk_modified)
            if disk_dt > kernel_dt:
                sync_needed = True
                reason = f"File modified at {disk_dt} after kernel started at {kernel_dt}"
        except:
            pass
    
    return json.dumps({
        'sync_needed': sync_needed,
        'reason': reason if sync_needed else "Kernel state appears synced with disk",
        'human_cells': human_cells,
        'human_cell_count': len(human_cells),
        'total_code_cells': sum(1 for c in nb.cells if c.cell_type == 'code'),
        'last_agent_execution': last_agent_time,
        'kernel_start_time': kernel_start_time,
        'recommendation': 'sync_state_from_disk' if sync_needed else 'proceed',
        'suggested_strategy': 'smart' if len(human_cells) < 10 else 'full'
    }, indent=2)

@mcp.tool()
def set_stop_on_error(notebook_path: str, enabled: bool):
    """
    Control whether execution queue stops on first error.
    Agent Use Case: Set to True when running dependent cells (cell 2 needs cell 1's variables).
    Set to False for independent exploration cells.
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return "Error: No running kernel. Call start_kernel first."
    
    session['stop_on_error'] = enabled
    return f"stop_on_error set to {enabled} for {notebook_path}"

@mcp.tool()
def get_notebook_outline(notebook_path: str):
    """
    Low-token overview of the file.
    Output: JSON list: [{index: 0, type: "code", source_preview: "import pandas...", state: "executed"}].
    """
    return notebook.get_notebook_outline(notebook_path)

@mcp.tool()
def append_cell(notebook_path: str, content: str, cell_type: str = "code"):
    """
    Add new logic to the end.
    Constraint: Automatically clears output (to avoid stale data) and sets execution_count to null.
    """
    return notebook.append_cell(notebook_path, content, cell_type)

@mcp.tool()
def edit_cell(notebook_path: str, index: int, content: str):
    """
    Replaces the Code. Crucially: Automatically clears the output.
    Why: If you change the code, the old output is now a lie. Clearing it prevents hallucinations.
    """
    return notebook.edit_cell(notebook_path, index, content)

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
    return notebook_ops.read_cell_smart(notebook_path, index, target, fmt, line_range)

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
    return notebook_ops.search_notebook(notebook_path, query, regex)

@mcp.tool()
async def get_kernel_info(notebook_path: str):
    """
    Check active variables without printing them.
    Returns: JSON dictionary of active variables, their types, and string representations (truncated).
    """
    return await session_manager.get_kernel_info(notebook_path)

# --- NEW ASYNC TOOLS ---

@mcp.tool()
async def run_cell_async(notebook_path: str, index: int):
    """
    Submits a cell for execution in the background.
    Returns: A Task ID (e.g., "b4f2...").
    Use `get_execution_status(task_id)` to check progress.
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return "Error: No running kernel. Call start_kernel first."
    
    # 1. Get Code
    try:
        cell = notebook.read_cell(notebook_path, index)
    except Exception as e:
        return f"Error reading cell: {e}"
        
    code = cell['source']
    
    # 2. Submit
    exec_id = await session_manager.execute_cell_async(notebook_path, index, code)
    if not exec_id:
        return "Error starting execution."
        
    return f"Execution started. Task ID: {exec_id}"

@mcp.tool()
def get_execution_status(notebook_path: str, task_id: str):
    """
    Checks the status of a background cell execution.
    Returns: JSON with 'status' (running/completed/error) and 'output' (so far).
    """
    status = session_manager.get_execution_status(notebook_path, task_id)
    return json.dumps(status, indent=2)

@mcp.tool()
def get_execution_stream(notebook_path: str, task_id: str, since_output_index: int = 0):
    """
    [PHASE 3.1] Get real-time streaming outputs from a running execution.
    
    This tool allows agents to monitor long-running cells (model training, large computations)
    by polling for new outputs without waiting for completion.
    
    Args:
        notebook_path: Path to the notebook file
        task_id: Execution ID returned by execute_cell_async
        since_output_index: Return only outputs after this index (for incremental polling)
    
    Returns:
        JSON with:
        - status: Current execution status (queued/running/completed/error)
        - new_outputs: Sanitized text of new outputs since last poll
        - next_index: Index to use for next poll (total output count)
        - last_activity: Timestamp of most recent output
    
    Agent Usage:
        exec_id = execute_cell_async(path, 0, "train_model(epochs=100)")
        output_idx = 0
        while True:
            stream = get_execution_stream(path, exec_id, output_idx)
            data = json.loads(stream)
            if data['new_outputs']:
                print(data['new_outputs'])  # "Epoch 12/100... loss: 0.342"
                output_idx = data['next_index']
            if data['status'] in ['completed', 'error']:
                break
            time.sleep(5)  # Poll every 5 seconds
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return json.dumps({"status": "error", "message": "No active kernel session"})
    
    # Check if still queued
    if task_id in session['queued_executions']:
        queued_data = session['queued_executions'][task_id]
        return json.dumps({
            "status": "queued",
            "new_outputs": "",
            "next_index": 0,
            "queued_time": queued_data.get('queued_time', 0),
            "cell_index": queued_data.get('cell_index')
        })
    
    # Find execution in active executions
    target_data = None
    for msg_id, data in session['executions'].items():
        if data['id'] == task_id:
            target_data = data
            break
    
    if not target_data:
        return json.dumps({"status": "not_found", "message": "Execution ID not found"})
    
    # Get new outputs since last poll
    all_outputs = target_data['outputs']
    new_outputs = all_outputs[since_output_index:]
    
    # Sanitize outputs (converts binary images to assets, strips ANSI, etc.)
    assets_dir = str(Path(notebook_path).parent / "assets")
    stream_text = utils.sanitize_outputs(new_outputs, assets_dir)
    
    return json.dumps({
        "status": target_data['status'],
        "new_outputs": stream_text,
        "next_index": len(all_outputs),
        "total_outputs": len(all_outputs),
        "last_activity": target_data.get('last_activity', 0),
        "cell_index": target_data.get('cell_index')
    }, indent=2)

@mcp.tool()
def check_kernel_resources(notebook_path: str):
    """
    [PHASE 3.4] Get CPU and RAM usage of the kernel process.
    
    Allows agents to monitor resource consumption and implement auto-restart logic
    to prevent memory leaks or runaway processes.
    
    Args:
        notebook_path: Path to the notebook file
    
    Returns:
        JSON with:
        - status: 'active' or error state
        - pid: Process ID of the kernel
        - memory_mb: Total RAM usage in MB (includes child processes)
        - memory_percent: RAM usage as percentage of system memory
        - cpu_percent: CPU usage percentage (includes child processes)
        - num_threads: Number of threads in kernel process
        - num_children: Number of child processes spawned
    
    Agent Usage:
        # Check before heavy computation
        resources = json.loads(check_kernel_resources(path))
        if resources['memory_percent'] > 80:
            stop_kernel(path)
            start_kernel(path)  # Fresh start
            print("Kernel restarted due to high memory usage")
        
        # Monitor during long-running task
        while status['status'] == 'running':
            resources = json.loads(check_kernel_resources(path))
            if resources['memory_mb'] > 8000:  # 8GB threshold
                interrupt_kernel(path)
                print("Interrupted: memory exceeded 8GB")
                break
    """
    result = session_manager.get_kernel_resources(notebook_path)
    return json.dumps(result, indent=2)

@mcp.tool()
async def run_all_cells(notebook_path: str):
    """
    Execute all code cells in the notebook sequentially.
    Returns: List of execution IDs for status tracking.
    Agent Use Case: Instead of 20 separate run_cell_async calls, use this single tool.
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return "Error: No running kernel. Call start_kernel first."
    
    # Read notebook
    try:
        nb = nbformat.read(notebook_path, as_version=4)
    except Exception as e:
        return f"Error reading notebook: {e}"
    
    # Queue all code cells
    exec_ids = []
    for idx, cell in enumerate(nb.cells):
        if cell.cell_type == 'code':
            exec_id = await session_manager.execute_cell_async(notebook_path, idx, cell.source)
            if exec_id:
                exec_ids.append({'cell_index': idx, 'exec_id': exec_id})
    
    return json.dumps({
        'message': f'Queued {len(exec_ids)} cells for execution',
        'executions': exec_ids
    }, indent=2)

@mcp.tool()
async def sync_state_from_disk(notebook_path: str, strategy: str = "smart"):
    """
    [HANDOFF PROTOCOL] Synchronize kernel state with disk after human intervention.
    
    **Critical Use Case**: When a human has edited the notebook externally (in VS Code, 
    JupyterLab, etc.), the kernel's RAM state is OUT OF SYNC with the disk. This tool 
    reconciles the "Split Brain" by re-executing cells to rebuild variable state.
    
    **When to Use**:
    - Agent resumes work after human editing session
    - Agent detects unexpected notebook structure (new cells, modified cells)
    - After switching from "Human Mode" to "Agent Mode" in VS Code extension
    
    **Strategies**:
    - "smart" (default): Only re-executes cells that define variables (skips plots, prints)
    - "full": Re-executes ALL code cells from disk (safest, but slowest)
    - "incremental": Only executes cells modified since last agent execution (requires metadata tracking)
    
    Args:
        notebook_path: Path to the notebook file
        strategy: Sync strategy ("smart", "full", or "incremental")
    
    Returns:
        JSON with:
        - cells_synced: Number of cells re-executed
        - execution_ids: List of execution IDs for tracking
        - skipped_cells: List of cell indices skipped (if strategy="smart")
        - sync_duration_estimate: Estimated time to complete (based on queue size)
    
    Agent Workflow Example:
        # 1. Agent detects notebook changed on disk
        outline = get_notebook_outline(path)
        if len(outline['cells']) > session.last_known_cell_count:
            # 2. Sync state before continuing
            result = sync_state_from_disk(path, strategy="smart")
            print(f"Synced {result['cells_synced']} cells to rebuild state")
        
        # 3. Now safe to continue work
        append_cell(path, "# Agent's new analysis")
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return json.dumps({
            "error": "No active kernel. Call start_kernel first.",
            "hint": "The kernel must be running to sync state."
        })
    
    # Read notebook from disk
    try:
        nb = nbformat.read(notebook_path, as_version=4)
    except Exception as e:
        return json.dumps({
            "error": f"Failed to read notebook from disk: {e}",
            "notebook_path": notebook_path
        })
    
    exec_ids = []
    skipped = []
    
    if strategy == "full":
        # Re-execute everything (safest)
        for idx, cell in enumerate(nb.cells):
            if cell.cell_type == 'code':
                exec_id = await session_manager.execute_cell_async(notebook_path, idx, cell.source)
                if exec_id:
                    exec_ids.append({'cell_index': idx, 'exec_id': exec_id})
    
    elif strategy == "smart":
        # Skip cells that don't define variables (optimization)
        import re
        
        for idx, cell in enumerate(nb.cells):
            if cell.cell_type != 'code':
                continue
            
            source = cell.source.strip()
            
            # Skip empty cells
            if not source:
                skipped.append({'cell_index': idx, 'reason': 'empty'})
                continue
            
            # Skip pure visualization (no assignments)
            if re.match(r'^(plt\.|fig\.|ax\.|sns\.|plot\(|show\()', source):
                skipped.append({'cell_index': idx, 'reason': 'visualization_only'})
                continue
            
            # Skip pure print statements
            if re.match(r'^(print\(|display\()', source) and '=' not in source:
                skipped.append({'cell_index': idx, 'reason': 'output_only'})
                continue
            
            # Execute cells that likely define state
            exec_id = await session_manager.execute_cell_async(notebook_path, idx, source)
            if exec_id:
                exec_ids.append({'cell_index': idx, 'exec_id': exec_id})
    
    elif strategy == "incremental":
        # Only execute cells modified since last agent run
        for idx, cell in enumerate(nb.cells):
            if cell.cell_type != 'code':
                continue
            
            # Check if cell was executed by agent (has mcp_trace metadata)
            metadata = cell.metadata.get('mcp_trace', {})
            
            # If no agent metadata OR cell source changed, re-execute
            # (This requires storing cell hash in metadata - future enhancement)
            # For now, fall back to "smart" strategy
            exec_id = await session_manager.execute_cell_async(notebook_path, idx, cell.source)
            if exec_id:
                exec_ids.append({'cell_index': idx, 'exec_id': exec_id})
    
    else:
        return json.dumps({
            "error": f"Unknown strategy: {strategy}",
            "valid_strategies": ["smart", "full", "incremental"]
        })
    
    # Calculate estimated sync duration
    queue_size = session['execution_queue'].qsize() if 'execution_queue' in session else 0
    estimate_seconds = len(exec_ids) * 2  # Rough estimate: 2s per cell
    
    return json.dumps({
        'status': 'syncing',
        'message': f'Queued {len(exec_ids)} cells for state synchronization',
        'cells_synced': len(exec_ids),
        'cells_skipped': len(skipped),
        'skipped_details': skipped,
        'execution_ids': exec_ids,
        'queue_size': queue_size + len(exec_ids),
        'estimated_duration_seconds': estimate_seconds,
        'strategy_used': strategy,
        'hint': 'Use get_execution_status() to monitor progress'
    }, indent=2)

@mcp.tool()
async def cancel_execution(notebook_path: str, task_id: str):
    """
    Interrupts the kernel to stop the running task.
    """
    return await session_manager.cancel_execution(notebook_path, task_id)

@mcp.tool()
async def get_variable_info(notebook_path: str, var_name: str):
    """
    Inspect a specific variable in the kernel without dumping all globals.
    Agent Use Case: Check 'df.columns' or 'df.shape' without loading the entire DataFrame.
    Returns: JSON with type, shape, columns, memory usage, preview, etc.
    """
    return await session_manager.get_variable_info(notebook_path, var_name)

@mcp.tool()
async def list_variables(notebook_path: str):
    """
    List all variables in the kernel (names and types only, no values).
    Agent Use Case: Discover what variables exist before using get_variable_info.
    """
    code = """
import json
import sys
result = []
for name in dir():
    if not name.startswith('_'):
        obj = globals()[name]
        if not isinstance(obj, type(sys)):  # Skip modules
            result.append({"name": name, "type": type(obj).__name__})
print(json.dumps(result))
"""
    return await session_manager.run_simple_code(notebook_path, code)

@mcp.tool()
async def inspect_variable(notebook_path: str, variable_name: str):
    """
    Surgical Inspection: Returns a human-readable markdown summary of a variable.
    
    Agent Use Case: 
    - Peek at DataFrames without loading 1GB of data into context
    - Inspect lists, dicts, models without full dumps
    - Get shape, columns, dtypes, and head(3) for DataFrames
    
    Returns: Markdown-formatted summary suitable for LLM consumption
    """
    # SECURITY FIX: Use safe dictionary lookup instead of eval()
    # This prevents code injection via inspect_variable(path, "os.system('rm -rf /')")
    code = f"""
import pandas as pd
import numpy as np

def _safe_inspect():
    var_name = '{variable_name}'
    
    # Safe lookup: Check locals then globals
    if var_name in locals():
        obj = locals()[var_name]
    elif var_name in globals():
        obj = globals()[var_name]
    else:
        return f"Variable '{{var_name}}' not found in current scope."
    
    try:
        t_name = type(obj).__name__
        output = [f"### Type: {{t_name}}"]
        
        if isinstance(obj, pd.DataFrame):
            output.append(f"- Shape: {{obj.shape}}")
            output.append(f"- Columns: {{list(obj.columns)}}")
            mem_mb = obj.memory_usage(deep=True).sum() / 1024**2
            output.append(f"- Memory: {{mem_mb:.2f}} MB")
            output.append("\\n#### Head (3 rows):")
            output.append(obj.head(3).to_markdown(index=False))
            
        elif isinstance(obj, pd.Series):
            output.append(f"- Length: {{len(obj)}}")
            output.append(f"- Dtype: {{obj.dtype}}")
            output.append("\\n#### Head (5 items):")
            output.append(obj.head(5).to_markdown())
            
        elif isinstance(obj, (list, tuple)):
            output.append(f"- Length: {{len(obj)}}")
            output.append(f"- Sample (first 5): {{obj[:5]}}")
            
        elif isinstance(obj, dict):
            output.append(f"- Keys: {{list(obj.keys())[:10]}}")
            output.append(f"- Sample (first 3 items):")
            for k, v in list(obj.items())[:3]:
                output.append(f"  - {{k}}: {{str(v)[:100]}}")
                
        elif hasattr(obj, 'shape') and hasattr(obj, 'dtype'):  # Numpy
            output.append(f"- Shape: {{obj.shape}}")
            output.append(f"- Dtype: {{obj.dtype}}")
            output.append(f"- Sample: {{list(obj.flat[:10])}}")
            
        else:
            output.append(f"- String Representation: {{str(obj)[:500]}}")
            
        return "\\n".join(output)
        
    except Exception as e:
        return f"Inspection error: {{e}}"

print(_safe_inspect())
"""
    return await session_manager.run_simple_code(notebook_path, code)

# -----------------------

@mcp.tool()
async def install_package(notebook_path: str, package_name: str):
    """Installs packages into the active kernel's environment."""
    return await session_manager.install_package(notebook_path, package_name)

@mcp.tool()
async def interrupt_kernel(notebook_path: str):
    """Stops the currently running cell immediately."""
    return await session_manager.interrupt_kernel(notebook_path)

@mcp.tool()
async def restart_kernel(notebook_path: str):
    """Restarts the kernel, clearing all variables but keeping outputs."""
    return await session_manager.restart_kernel(notebook_path)

@mcp.tool()
async def check_working_directory(notebook_path: str):
    """Checks the current working directory (CWD) of the active kernel."""
    code = "import os; print(os.getcwd())"
    return await session_manager.run_simple_code(notebook_path, code)

@mcp.tool()
async def set_working_directory(notebook_path: str, path: str):
    """Changes the CWD of the kernel."""
    # Escape backslashes for Windows
    safe_path = path.replace("\\", "/")
    code = f"import os; os.chdir('{safe_path}'); print(os.getcwd())"
    result = await session_manager.run_simple_code(notebook_path, code)
    if "Error" in result:
        return result
    return f"Working directory changed to: {result}"

@mcp.tool()
async def list_kernel_packages(notebook_path: str):
    """Lists packages installed in the active kernel's environment."""
    # We run this inside python to avoid OS shell syntax differences
    code = """
import pkg_resources
installed = sorted([(d.project_name, d.version) for d in pkg_resources.working_set])
for p, v in installed:
    print(f"{p}=={v}")
"""
    return await session_manager.run_simple_code(notebook_path, code)

@mcp.tool()
def list_available_environments():
    """Scans the system for Python environments (venvs, conda, etc)."""
    envs = session_manager.list_environments()
    return json.dumps(envs, indent=2)

@mcp.tool()
async def switch_kernel_environment(notebook_path: str, venv_path: str):
    """
    Stops the current kernel and restarts it using the specified environment path.
    path: The absolute path to the environment root (not the bin/python executable).
    """
    # 1. Stop
    await session_manager.stop_kernel(notebook_path)
    
    # 2. Start with new env
    result = await session_manager.start_kernel(notebook_path, venv_path)
    return f"Switched Environment. {result}"

# ============================================================================
# NEW TOOLS - Notebook Creation and Management
# ============================================================================

@mcp.tool()
def create_notebook(
    notebook_path: str,
    kernel_name: str = "python3",
    kernel_display_name: Optional[str] = None,
    language: str = "python",
    python_version: Optional[str] = None,
    initial_cells: Optional[str] = None
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
        cells
    )

# ============================================================================
# Cell Manipulation Tools
# ============================================================================

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

# ============================================================================
# Metadata Operations
# ============================================================================

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
def update_kernelspec(notebook_path: str, kernel_name: str, display_name: Optional[str] = None, language: Optional[str] = None):
    """Updates the kernelspec in notebook metadata."""
    return notebook.update_kernelspec(notebook_path, kernel_name, display_name, language)

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

# ============================================================================
# Output Operations
# ============================================================================

@mcp.tool()
def clear_cell_outputs(notebook_path: str, index: int):
    """Clears outputs from a specific cell."""
    return notebook.clear_cell_outputs(notebook_path, index)

@mcp.tool()
def clear_all_outputs(notebook_path: str):
    """Clears outputs from all code cells in the notebook."""
    return notebook.clear_all_outputs(notebook_path)

@mcp.tool()
def get_cell_outputs(notebook_path: str, index: int):
    """Gets the outputs from a specific cell as JSON."""
    outputs = notebook.get_cell_outputs(notebook_path, index)
    return json.dumps(outputs, indent=2)

# ============================================================================
# Validation
# ============================================================================

@mcp.tool()
def validate_notebook(notebook_path: str):
    """Validates notebook structure and returns any issues."""
    result = notebook.validate_notebook(notebook_path)
    return json.dumps(result, indent=2)

# ============================================================================
# Environment Detection and Management
# ============================================================================

@mcp.tool()
def find_python_executables():
    """
    Discovers all Python interpreters on the system.
    Scans PATH and common installation locations.
    Returns JSON list of discovered interpreters with version and type info.
    """
    executables = environment.find_python_executables()
    return json.dumps(executables, indent=2)

@mcp.tool()
def validate_python_executable(python_path: str):
    """
    Validates a Python executable.
    Returns detailed validation results including version and pip availability.
    """
    result = environment.validate_python_executable(python_path)
    return json.dumps(result, indent=2)

@mcp.tool()
def auto_detect_environment(notebook_path: Optional[str] = None):
    """
    Automatically detects the best Python environment to use.
    If notebook_path is provided, looks for .venv or environment in notebook directory.
    Returns JSON with python_path, env_type, env_name, and version.
    """
    result = environment.auto_detect_environment(notebook_path)
    return json.dumps(result, indent=2)

@mcp.tool()
def create_venv(path: str, python_executable: str = ""):
    """
    Creates a new virtual environment.
    path: Path where the venv will be created
    python_executable: Optional Python executable to use (defaults to sys.executable)
    """
    if python_executable:
        result = environment.create_venv(path, python_executable)
    else:
        result = environment.create_venv(path, sys.executable)
    return json.dumps(result, indent=2)

if __name__ == "__main__":
    try:
        mcp.run()
    finally:
        asyncio.run(session_manager.shutdown_all())
