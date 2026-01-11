from mcp.server.fastmcp import FastMCP
import asyncio
from pathlib import Path
from typing import List, Optional
import nbformat
import json
import sys
import logging
import datetime
from src.session import SessionManager
from src import notebook, utils, environment

# Configure logging to stderr to avoid corrupting JSON-RPC stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

mcp = FastMCP("jupyter")
session_manager = SessionManager()
session_manager.set_mcp_server(mcp)

# Persistence for proposals
PROPOSAL_STORE_FILE = Path.home() / ".mcp-jupyter" / "proposals.json"

def load_proposals():
    """Load proposals from disk to survive server restarts."""
    if PROPOSAL_STORE_FILE.exists():
        try:
            with open(PROPOSAL_STORE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load proposals: {e}")
    return {}

def save_proposals():
    """Save proposals to disk."""
    try:
        PROPOSAL_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROPOSAL_STORE_FILE, 'w') as f:
            json.dump(PROPOSAL_STORE, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save proposals: {e}")

# Store for agent proposals to support feedback loop
# Key: proposal_id, Value: dict with status, result, timestamp
PROPOSAL_STORE = load_proposals()

@mcp.tool()
async def start_kernel(notebook_path: str, venv_path: str = "", docker_image: str = "", timeout: int = 300):
    """
    Boot a background process.
    Windows Logic: Looks for venv_path/Scripts/python.exe.
    Ubuntu Logic: Looks for venv_path/bin/python.
    Docker Logic: If docker_image is set, runs kernel securely in container.
    Timeout: Seconds before killing long-running cells (default: 300).
    Output: "Kernel started (PID: 1234). Ready for execution."
    """
    # Capture the active session for notifications
    try:
        ctx = mcp.get_context()
        if ctx and ctx.request_context:
            session_manager.register_session(ctx.request_context.session)
    except:
         # Ignore if context not available (e.g. testing)
         pass

    # Security Check
    if not docker_image:
        logger.warning(f"Unsandboxed execution requested for {notebook_path}. All code runs with user privileges.")

    return await session_manager.start_kernel(
        notebook_path, 
        venv_path if venv_path else None,
        docker_image if docker_image else None,
        timeout
    )

@mcp.tool()
async def stop_kernel(notebook_path: str):
    """
    Kill the process to free RAM and clean up assets.
    """
    # 1. Prune assets before stopping
    from src.asset_manager import prune_unused_assets
    try:
        # Run cleanup. This ensures that if I delete a cell and close the notebook,
        # the orphaned image is deleted.
        prune_unused_assets(notebook_path, dry_run=False)
    except Exception as e:
        logger.warning(f"Asset cleanup failed: {e}")

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
async def detect_sync_needed(notebook_path: str):
    """
    [HANDOFF PROTOCOL] Detect if kernel state is out of sync with disk.
    
    **Purpose**: Before the agent starts work, check if a human has modified the notebook
    since the last agent execution.
    
    **How It Works**:
    1. Reads notebook from disk.
    2. Calculates SHA-256 hash of each cell's content.
    3. Compares with 'execution_hash' stored in cell metadata.
    4. If hashes mismatch, sync is required.
    
    Returns:
        JSON with:
        - sync_needed: boolean
        - reason: Description of mismatch
        - changed_cells: List of cell indices that changed
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
    except Exception as e:
        return json.dumps({
            "error": f"Failed to read notebook: {e}"
        })
    
    changed_cells = []
    
    for idx, cell in enumerate(nb.cells):
        if cell.cell_type == 'code':
            current_hash = utils.get_cell_hash(cell.source)
            # Check both new 'mcp' and legacy 'mcp_trace' metadata locations
            mcp_meta = cell.metadata.get('mcp', {}) or cell.metadata.get('mcp_trace', {})
            last_hash = mcp_meta.get('execution_hash')
            
            # If no hash exists (never executed by agent) or hash mismatch (content changed)
            if not last_hash or current_hash != last_hash:
                changed_cells.append(idx)
    
    sync_needed = len(changed_cells) > 0
    
    return json.dumps({
        'sync_needed': sync_needed,
        'reason': f"Content mismatch in {len(changed_cells)} cells" if sync_needed else "Content matches execution history",
        'changed_cells': changed_cells,
        'recommendation': 'sync_state_from_disk' if sync_needed else 'proceed',
        'sync_strategy': 'full'
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
def get_notebook_outline(notebook_path: str, structure_override: Optional[List[dict]] = None):
    """
    Low-token overview of the file.
    Args:
        structure_override: Optional list of cell metadata pushed from VS Code buffer.
                           Prevents "Index Blindness" where Agent reads stale disk state.
    """
    if structure_override:
        # Use the real-time buffer state from VS Code
        return notebook.format_outline(structure_override)
    else:
        # Fallback to disk (risk of stale data)
        return notebook.get_notebook_outline(notebook_path)

@mcp.tool()
def append_cell(notebook_path: str, content: str, cell_type: str = "code"):
    """
    Add new logic to the end.
    Constraint: Automatically clears output (to avoid stale data) and sets execution_count to null.
    """
    return notebook.append_cell(notebook_path, content, cell_type)

@mcp.tool()
async def save_checkpoint(notebook_path: str, name: str = "checkpoint"):
    """
    Snapshot the current kernel variables (memory heap) to disk.
    Use this to prevent "Data Gravity" issues.
    """
    return await session_manager.save_checkpoint(notebook_path, name)

@mcp.tool()
async def load_checkpoint(notebook_path: str, name: str = "checkpoint"):
    """
    Restore variables from a disk snapshot.
    Replaces "Re-run all cells" strategy.
    """
    return await session_manager.load_checkpoint(notebook_path, name)

@mcp.tool()
def propose_edit(notebook_path: str, index: int, new_content: str):
    """
    Propose an edit to a cell. 
    This avoids writing to disk directly, preventing conflicts with the editor buffer.
    The Agent should use this instead of 'edit_cell'.
    """
    import uuid
    proposal_id = str(uuid.uuid4())
    
    # Construct proposal
    proposal = {
        "id": proposal_id,
        "action": "edit_cell",
        "notebook_path": notebook_path,
        "index": index,
        "new_content": new_content,
        "timestamp": str(datetime.datetime.now())
    }
    
    # We return a specific structure that the Client (mcpClient.ts) listens for.
    # By convention, if the tool result contains this structure, the client
    # will trigger a WorkspaceEdit.
    
    return json.dumps({
        "status": "proposal_created", 
        "proposal_id": proposal_id,
        "proposal": proposal,
        "message": "Edit proposed. Client must apply changes.",
        # SIGNAL PROTOCOL
        "_mcp_action": "apply_edit" 
    })

@mcp.tool()
def notify_edit_result(notebook_path: str, proposal_id: str, status: str, message: Optional[str] = None):
    """
    Callback for the client to report the result of a proposed edit.
    status: 'accepted' | 'rejected' | 'failed'
    """
    logger.info(f"Edit result for {notebook_path} (ID: {proposal_id}): {status} - {message}")
    
    # Store result for agent to retrieve
    timestamp = str(datetime.datetime.now())
    if proposal_id:
        PROPOSAL_STORE[proposal_id] = {
            "status": status,
            "message": message,
            "notebook_path": notebook_path,
            "timestamp": timestamp
        }
        save_proposals()
    
    return json.dumps({
        "status": "ack",
        "proposal_id": proposal_id,
        "timestamp": timestamp
    })

@mcp.tool()
def get_proposal_status(proposal_id: str):
    """
    Check the status of a specific proposal.
    Returns: 'pending', 'accepted', 'rejected', 'failed', or 'unknown'.
    """
    if proposal_id in PROPOSAL_STORE:
        return json.dumps(PROPOSAL_STORE[proposal_id])
    return json.dumps({"status": "unknown"})

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
async def get_kernel_info(notebook_path: str):
    """
    Check active variables without printing them.
    Returns: JSON dictionary of active variables, their types, and string representations (truncated).
    """
    return await session_manager.get_kernel_info(notebook_path)

# --- NEW ASYNC TOOLS ---

@mcp.tool()
async def run_cell_async(notebook_path: str, index: int, code_override: Optional[str] = None, task_id_override: Optional[str] = None):
    """
    Submits a cell for execution in the background.
    
    Args:
        notebook_path: Path to the notebook
        index: Cell index
        code_override: Optional explicit code to run (bypass disk read). 
                      Crucial for "File vs Buffer" race conditions.
        task_id_override: Optional client-generated ID to prevent race conditions.
    
    Returns: A Task ID (e.g., "b4f2...").
    Use `get_execution_status(task_id)` to check progress.
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return "Error: No running kernel. Call start_kernel first."
    
    # 1. Get Code (Buffer Priority)
    if code_override is not None:
        code = code_override
    else:
        # Fallback to disk (Legacy/test behavior)
        try:
            cell = notebook.read_cell(notebook_path, index)
            code = cell['source']
        except Exception as e:
            return f"Error reading cell: {e}"
    
    # 2. Submit
    exec_id = await session_manager.execute_cell_async(notebook_path, index, code, exec_id=task_id_override)
    if not exec_id:
        return "Error starting execution."
        
    return json.dumps({
        "task_id": exec_id,
        "message": "Execution started"
    })

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
    sanitized_json = utils.sanitize_outputs(new_outputs, assets_dir)
    
    # Unpack to avoid double-JSON encoding
    try:
        new_outputs_data = json.loads(sanitized_json)
    except:
        new_outputs_data = sanitized_json

    return json.dumps({
        "status": target_data['status'],
        "new_outputs": new_outputs_data,
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
async def sync_state_from_disk(notebook_path: str, strategy: str = "full"):
    """
    [HANDOFF PROTOCOL] Synchronize kernel state with disk after human intervention.
    
    **Critical Use Case**: When a human has edited the notebook externally (in VS Code, 
    JupyterLab, etc.), the kernel's RAM state is OUT OF SYNC with the disk. This tool 
    reconciles the "Split Brain" by re-executing cells to rebuild variable state.
    
    **When to Use**:
    - Agent resumes work after human editing session
    - Agent detects unexpected notebook structure (new cells, modified cells)
    - After switching from "Human Mode" to "Agent Mode" in VS Code extension
    
    **Strategy**:
    - Always uses "full" sync: Re-executes ALL code cells from disk
    - Previous "smart" strategy removed due to false positive risk
      (Example: cell with plt.figure() + data = calc() would skip calc() causing undefined variable errors)
    
    Args:
        notebook_path: Path to the notebook file
        strategy: DEPRECATED - now always uses "full" for correctness
    
    Returns:
        JSON with:
        - cells_synced: Number of cells re-executed
        - execution_ids: List of execution IDs for tracking
        - sync_duration_estimate: Estimated time to complete (based on queue size)
    
    Agent Workflow Example:
        # 1. Agent detects notebook changed on disk
        outline = get_notebook_outline(path)
        if len(outline['cells']) > session.last_known_cell_count:
            # 2. Sync state before continuing
            result = sync_state_from_disk(path)
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
    
    # [Sync Strategy 2.0: Cut-Point incremental Sync]
    # We find the first cell that is either changed OR not executed in this session.
    # We execute that cell and ALL subsequent cells to ensure consistent state.
    # This avoids re-running expensive early cells (Model Training, ETL) if they are unchanged.
    
    start_index = 0
    strategy_used = "incremental"
    
    if strategy == "full":
        # User requested full re-run
        start_index = 0
        strategy_used = "full"
    else:
        # Determine Cut Point
        first_dirty_idx = -1
        executed_indices = session.get('executed_indices', set())
        
        for idx, cell in enumerate(nb.cells):
            if cell.cell_type == 'code':
                # Condition 1: Not executed in this session (State missing)
                if idx not in executed_indices:
                    first_dirty_idx = idx
                    break 
                
                # Condition 2: Content Changed vs Disk
                current_hash = utils.get_cell_hash(cell.source)
                # Check both new 'mcp' and legacy 'mcp_trace'
                mcp_meta = cell.metadata.get('mcp', {}) or cell.metadata.get('mcp_trace', {})
                last_hash = mcp_meta.get('execution_hash')
                
                if not last_hash or current_hash != last_hash:
                    first_dirty_idx = idx
                    break
        
        if first_dirty_idx != -1:
            start_index = first_dirty_idx
        else:
            # All cells clean and executed
            start_index = len(nb.cells) # Nothing to run
            strategy_used = "incremental (skipped_all)"

    for idx, cell in enumerate(nb.cells):
        if cell.cell_type == 'code' and idx >= start_index:
            exec_id = await session_manager.execute_cell_async(notebook_path, idx, cell.source)
            if exec_id:
                exec_ids.append({'cell_index': idx, 'exec_id': exec_id})
    
    # Calculate estimated sync duration
    queue_size = session['execution_queue'].qsize() if 'execution_queue' in session else 0
    estimate_seconds = len(exec_ids) * 2  # Rough estimate: 2s per cell
    
    return json.dumps({
        'status': 'syncing',
        'message': f'Queued {len(exec_ids)} cells for state synchronization (starting from cell {start_index})',
        'cells_synced': len(exec_ids),
        'execution_ids': exec_ids,
        'queue_size': queue_size + len(exec_ids),
        'estimated_duration_seconds': estimate_seconds,
        'strategy_used': strategy_used,
        'hint': 'Use get_execution_status() to monitor progress.'
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
    # 1. Input Validation (Prevent Injection)
    if not variable_name.isidentifier():
        return f"Error: '{variable_name}' is not a valid Python identifier. Cannot inspect."

    # SECURITY FIX: Use pre-defined helper function instead of sending code blocks
    # Logic is defined in session.py startup_code as _mcp_inspect(name)
    code = f"_mcp_inspect('{variable_name}')"
    # Note: run_simple_code executes the expression and returns the result (relying on displayhook or print?)
    # SessionManager.run_simple_code runs using execute_cell logic which captures output.
    # _mcp_inspect returns a string. To get it as output, we might need to print it or rely on it being the last expression.
    # Jupyter usually displays the last expression.
    
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
def get_asset_content(asset_path: str) -> str:
    """
    Retrieve base64-encoded content of an asset file (PNG, PDF, SVG, etc.).
    
    **Use Case**: When the server reports `[PNG SAVED: assets/xyz.png]` and you need
    to analyze the image content with multimodal capabilities.
    
    **Security**: Only allows access to assets/ directory (prevents path traversal).
    
    Args:
        asset_path: Relative path to asset, typically from execution output
                   Format: "assets/asset_abc123.png" or just "asset_abc123.png"
    
    Returns:
        JSON with:
        - mime_type: MIME type of the asset (e.g., "image/png")
        - data: Base64-encoded binary content
        - size_bytes: Size of the encoded data
        - filename: Original filename
    
    Agent Workflow Example:
        # 1. Execute cell that generates plot
        result = execute_cell(path, 0, "import matplotlib.pyplot as plt\\nplt.plot([1,2,3])")
        # Output: "[PNG SAVED: assets/asset_abc123.png]"
        
        # 2. Retrieve asset for analysis
        asset = get_asset_content("assets/asset_abc123.png")
        # Now can pass asset['data'] to multimodal model for description
    """
    import base64
    from pathlib import Path
    
    # Normalize path separators
    asset_path = asset_path.replace("\\", "/")
    
    # Security: Extract just the filename if full path provided
    # Allows "assets/file.png" or just "file.png"
    path_parts = asset_path.split("/")
    if len(path_parts) > 1 and path_parts[0] == "assets":
        filename = path_parts[-1]
    else:
        filename = path_parts[-1]
    
    # Build full path relative to current working directory
    # Assets are always stored in assets/ subdirectory
    full_path = Path("assets") / filename
    
    # Security check: Verify resolved path is still within assets directory
    try:
        resolved = full_path.resolve()
        assets_dir = Path("assets").resolve()
        if not str(resolved).startswith(str(assets_dir)):
            return json.dumps({
                "error": "Security violation: Path traversal attempt blocked",
                "requested_path": asset_path
            })
    except Exception as e:
        return json.dumps({
            "error": f"Invalid path: {str(e)}",
            "requested_path": asset_path
        })
    
    # Check if file exists
    if not full_path.exists():
        return json.dumps({
            "error": f"Asset not found: {asset_path}",
            "checked_path": str(full_path),
            "hint": "Ensure the cell has been executed and produced output. Check execution status."
        })
    
    # Determine MIME type from extension
    mime_map = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.svg': 'image/svg+xml',
        '.pdf': 'application/pdf',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    suffix = full_path.suffix.lower()
    mime_type = mime_map.get(suffix, 'application/octet-stream')
    
    # Read and encode
    try:
        with open(full_path, 'rb') as f:
            raw_bytes = f.read()
            data = base64.b64encode(raw_bytes).decode('utf-8')
        
        return json.dumps({
            "mime_type": mime_type,
            "data": data,
            "size_bytes": len(raw_bytes),
            "encoded_size": len(data),
            "filename": filename,
            "full_path": str(full_path)
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "error": f"Failed to read asset: {str(e)}",
            "asset_path": str(full_path)
        })

@mcp.tool()
def edit_cell_by_id(notebook_path: str, cell_id: str, content: str, expected_index: Optional[int] = None):
    """
    [GIT-SAFE] Edit cell by stable Cell ID instead of index.
    
    **Why Cell IDs**: Index-based addressing breaks when cells are added/deleted.
    Cell IDs are stable UUIDs that survive notebook restructuring.
    
    **Pre-flight Validation**: If expected_index is provided, checks that the cell
    hasn't moved since the agent last read the outline. Prevents overwriting wrong cell.
    
    Args:
        notebook_path: Path to notebook
        cell_id: Cell ID from get_notebook_outline (e.g., "89523d2a-...")
        content: New cell content
        expected_index: Optional - cell's last known index for staleness check
    
    Returns:
        Success message or StaleStateError
    
    Agent Workflow:
        # 1. Get current outline
        outline = get_notebook_outline(path)
        cell = outline[5]  # Edit 6th cell
        
        # 2. Edit by ID with validation
        result = edit_cell_by_id(
            path, 
            cell_id=cell['id'],
            content="import pandas as pd",
            expected_index=cell['index']  # Prevents race conditions
        )
    """
    from src.cell_id_manager import edit_cell_by_id as _edit_by_id, StaleStateError
    
    try:
        return _edit_by_id(notebook_path, cell_id, content, expected_index)
    except StaleStateError as e:
        return json.dumps({
            "error": "StaleStateError",
            "message": str(e),
            "action_required": "Call get_notebook_outline() to refresh cell positions and retry"
        }, indent=2)

@mcp.tool()
def delete_cell_by_id(notebook_path: str, cell_id: str, expected_index: Optional[int] = None):
    """
    [GIT-SAFE] Delete cell by stable Cell ID.
    
    See edit_cell_by_id for rationale on Cell ID addressing.
    """
    from src.cell_id_manager import delete_cell_by_id as _delete_by_id, StaleStateError
    
    try:
        return _delete_by_id(notebook_path, cell_id, expected_index)
    except StaleStateError as e:
        return json.dumps({
            "error": "StaleStateError",
            "message": str(e),
            "action_required": "Call get_notebook_outline() to refresh and retry"
        }, indent=2)

@mcp.tool()
def insert_cell_by_id(notebook_path: str, after_cell_id: Optional[str], content: str, cell_type: str = "code"):
    """
    [GIT-SAFE] Insert new cell after specified Cell ID.
    
    Args:
        notebook_path: Path to notebook
        after_cell_id: Insert after this Cell ID (None = prepend to start)
        content: Cell content
        cell_type: 'code' or 'markdown'
    
    Returns:
        Success message with new cell's ID
    """
    from src.cell_id_manager import insert_cell_by_id as _insert_by_id, StaleStateError
    
    try:
        return _insert_by_id(notebook_path, after_cell_id, content, cell_type)
    except StaleStateError as e:
        return json.dumps({
            "error": "StaleStateError",
            "message": str(e),
            "action_required": "Call get_notebook_outline() to refresh and retry"
        }, indent=2)

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

# ============================================================================
# Git-Awareness Tools (Git-Safe Workflow)
# ============================================================================

@mcp.tool()
def save_notebook_clean(notebook_path: str, strip_outputs: bool = False):
    """
    [GIT-SAFE] Save notebook in Git-friendly format.
    
    Strips volatile metadata while keeping outputs for GitHub viewing:
    - execution_count (set to null)
    - Volatile cell metadata (timestamps, collapsed, scrolled)
    - Optionally strips all outputs if strip_outputs=True
    
    **When to use**: Call this before git commit to minimize merge conflicts.
    
    Args:
        notebook_path: Path to notebook file
        strip_outputs: If True, also remove all outputs (for sensitive data)
    
    Returns:
        Success message with count of cleaned cells
    
    Example:
        # Before committing
        save_notebook_clean("analysis.ipynb")
        # Then: git add analysis.ipynb && git commit
    """
    from src.git_tools import save_notebook_clean as _save_clean
    return _save_clean(notebook_path, strip_outputs)

@mcp.tool()
def setup_git_filters(repo_path: str = "."):
    """
    [GIT-SAFE] Configure Git filters for automatic notebook cleaning.
    
    One-time setup per repository. Installs nbstripout filter that:
    - Auto-strips execution_count on commit
    - Auto-strips volatile metadata
    - Keeps outputs in working tree (for local viewing)
    
    **When to use**: Run once when starting work on a new repo with notebooks.
    
    Args:
        repo_path: Path to Git repository root (default: current directory)
    
    Returns:
        Success message or error with installation instructions
    
    Example:
        setup_git_filters(".")
        # Now all git commits will auto-clean notebooks
    """
    from src.git_tools import setup_git_filters as _setup_filters
    return _setup_filters(repo_path)

@mcp.tool()
def create_agent_branch(repo_path: str = ".", branch_name: str = ""):
    """
    [GIT-SAFE] Create defensive Git branch for agent work.
    
    Safety checks:
    - Fails if uncommitted changes exist
    - Fails if in detached HEAD state
    - Creates and checks out new branch
    
    **Critical for safety**: Agent should ALWAYS work on a separate branch.
    Human can review and squash-merge when done.
    
    Args:
        repo_path: Path to Git repository
        branch_name: Branch name (default: agent/task-{timestamp})
    
    Returns:
        Success message with branch name and merge instructions
    
    Example:
        create_agent_branch(".", "agent/add-features")
        # Now safely work on this branch
        # Human will review and merge later
    """
    from src.git_tools import create_agent_branch as _create_branch
    return _create_branch(repo_path, branch_name)

@mcp.tool()
def commit_agent_work(repo_path: str = ".", message: str = "", files: Optional[List[str]] = None):
    """
    [GIT-SAFE] Commit agent changes to current branch.
    
    Safety checks:
    - Only commits specified files (no 'git add .')
    - Refuses to commit to main/master
    - Runs pre-commit hooks
    
    **Optional helper**: Agent can also just tell human to review and commit.
    
    Args:
        repo_path: Path to Git repository
        message: Commit message (required)
        files: List of file paths to commit (required)
    
    Returns:
        Success message with commit hash, or error
    
    Example:
        save_notebook_clean("analysis.ipynb")
        commit_agent_work(".", "Add data analysis", ["analysis.ipynb"])
    """
    from src.git_tools import commit_agent_work as _commit_work
    return _commit_work(repo_path, message, files)

@mcp.tool()
def prune_unused_assets(notebook_path: str, dry_run: bool = False):
    """
    [GIT-SAFE] Delete asset files not referenced in notebook.
    
    Scans notebook for asset references, deletes orphaned files.
    Safe to run periodically to clean up after cell deletions.
    
    Args:
        notebook_path: Path to notebook file
        dry_run: If True, only report what would be deleted
    
    Returns:
        JSON with deleted/kept files and size freed
    
    Example:
        # Check what would be deleted
        prune_unused_assets("analysis.ipynb", dry_run=True)
        # Actually delete
        prune_unused_assets("analysis.ipynb")
    """
    from src.asset_manager import prune_unused_assets as _prune_assets
    result = _prune_assets(notebook_path, dry_run)
    return json.dumps(result, indent=2)

@mcp.tool()
def get_assets_summary(notebook_path: str):
    """
    [GIT-SAFE] Get summary of asset usage for a notebook.
    
    Returns counts and sizes of assets (total, referenced, orphaned).
    Useful to understand storage impact before/after cleanup.
    
    Args:
        notebook_path: Path to notebook file
    
    Returns:
        JSON with asset statistics
    
    Example:
        get_assets_summary("analysis.ipynb")
        # Shows: 50 total assets, 30 referenced, 20 orphaned
    """
    from src.asset_manager import get_assets_summary as _get_summary
    result = _get_summary(notebook_path)
    return json.dumps(result, indent=2)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", default="stdio", choices=["stdio", "websocket", "sse"])
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()

    try:
        # Restore any persisted sessions from previous server runs
        asyncio.run(session_manager.restore_persisted_sessions())
        
        if args.transport == "websocket":
            import uvicorn
            from starlette.applications import Starlette
            from starlette.routing import WebSocketRoute
            from starlette.websockets import WebSocket
            from mcp.server.websocket import websocket_server
            
            async def mcp_websocket_endpoint(websocket: WebSocket):
                async with websocket_server(websocket.scope, websocket.receive, websocket.send) as (read_stream, write_stream):
                    await mcp._mcp_server.run(
                        read_stream,
                        write_stream,
                        mcp._mcp_server.create_initialization_options(),
                    )

            app = Starlette(
                routes=[
                    WebSocketRoute("/ws", mcp_websocket_endpoint)
                ]
            )
            
            # Print port to stderr so parent process can parse it if needed
            print(f"MCP Server listening on ws://127.0.0.1:{args.port}/ws", file=sys.stderr)
            
            # Run uvicorn
            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="error")
             
        else:
            # Start the MCP server using Standard IO
            mcp.run()
    finally:
        asyncio.run(session_manager.shutdown_all())
