"""
Execution Tools - Code execution tools.

Includes: run_cell_async, get_execution_status, is_kernel_busy, 
check_kernel_resources, run_all_cells, cancel_execution, submit_input
"""

import json
import nbformat
from typing import Optional
from src import notebook
from src.observability import get_logger
from src.validation import validated_tool
from src.models import (
    RunCellArgs, RunAllCellsArgs, CancelExecutionArgs, SubmitInputArgs
)

logger = get_logger(__name__)


def register_execution_tools(mcp, session_manager):
    """Register code execution tools with the MCP server."""
    
    @mcp.tool()
    @validated_tool(RunCellArgs)
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
        
        Raises:
            RuntimeError: If execution queue is full (HTTP 429 equivalent)
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
        
        # 2. Submit (with backpressure handling)
        try:
            exec_id = await session_manager.execute_cell_async(notebook_path, index, code, exec_id=task_id_override)
            if not exec_id:
                return "Error starting execution."
                
            return json.dumps({
                "task_id": exec_id,
                "message": "Execution started"
            })
        except RuntimeError as e:
            # [SECURITY] Backpressure: Queue is full
            return json.dumps({
                "error": "queue_full",
                "message": str(e),
                "http_equivalent": 429,
                "retry_after_seconds": 5
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
    def is_kernel_busy(notebook_path: str):
        """
        [PERFORMANCE] Check if kernel is currently executing or has queued work.
        
        Used by UI components (like variable dashboard) to skip polling when kernel is busy.
        Prevents flooding the execution queue with inspection requests during long-running operations.
        
        Args:
            notebook_path: Path to the notebook
            
        Returns:
            JSON with 'is_busy' (boolean) and optional 'reason' string
            
        Example:
            {"is_busy": true, "reason": "Executing cell 5"}
            {"is_busy": false}
        """
        is_busy = session_manager.is_kernel_busy(notebook_path)
        
        result = {"is_busy": is_busy}
        
        if is_busy:
            # Optionally provide more context about why it's busy
            session = session_manager.get_session(notebook_path)
            if session:
                if session['queued_executions']:
                    result["reason"] = f"{len(session['queued_executions'])} executions queued"
                else:
                    # Check active executions
                    active_count = sum(1 for data in session['executions'].values() if data['status'] in ['busy', 'queued'])
                    if active_count > 0:
                        result["reason"] = f"{active_count} executions running"
        
        return json.dumps(result)

    @mcp.tool()
    def check_kernel_resources(notebook_path: str):
        """
        [PHASE 3.4] Get CPU and RAM usage of the kernel process.
        
        Allows agents to monitor resource consumption and implement auto-restart logic
        to prevent memory leaks or runaway processes.
        """
        result = session_manager.get_kernel_resources(notebook_path)
        
        # [STATE CONTAMINATION] Inject CWD so UI can show "Agent Changed Directory" warning
        try:
             # CWD is already tracked in session or can be fetched
             # But getting it reliably might require a kernel call if not cached or tracked in session
             # For now, let's assume session_manager tracks it or we can just append it if available
             session = session_manager.get_session(notebook_path)
             if session:
                 # In session.py, we might need to update how we track this, 
                 # but let's see if we can get it from the session dict if it was updated by set_working_directory
                 # The 'cwd' field might exist in session dict if we update list_kernels to use it
                 result['cwd'] = session.get('cwd')
        except Exception:
             pass
             
        return json.dumps(result, indent=2)

    @mcp.tool()
    @validated_tool(RunAllCellsArgs)
    async def run_all_cells(notebook_path: str, force: bool = False):
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
        queue_full_count = 0
        skipped_count = 0
        
        for idx, cell in enumerate(nb.cells):
            if cell.cell_type == 'code':
                # [COST OF CURIOSITY] Check for expensive/frozen tags
                # e.g. # @frozen, # @expensive, # @skip
                source = cell.source.strip()
                should_skip = False
                skip_reason = ""
                
                if not force:
                    first_line = source.split('\n')[0].lower() if source else ""
                    if "# @frozen" in first_line or "# @skip" in first_line:
                        should_skip = True
                        skip_reason = "frozen"
                    elif "# @expensive" in first_line:
                        should_skip = True
                        skip_reason = "expensive"
                
                if should_skip:
                    skipped_count += 1
                    logger.info(f"Skipping cell {idx} due to tag: {skip_reason}")
                    continue

                try:
                    exec_id = await session_manager.execute_cell_async(notebook_path, idx, cell.source)
                    if exec_id:
                        exec_ids.append({'cell_index': idx, 'exec_id': exec_id})
                except RuntimeError as e:
                    # Queue is full, skip remaining cells
                    queue_full_count += 1
                    if queue_full_count == 1:  # Log once
                        logger.warning(f"[BACKPRESSURE] Queue full during run_all, stopped at cell {idx}")
                    break
        
        if queue_full_count > 0:
            return json.dumps({
                'status': 'partial',
                'message': f'Queue became full. Queued {len(exec_ids)} cells before hitting limit.',
                'executions': exec_ids,
                'queue_full': True,
                'retry_after_seconds': 5
            }, indent=2)
            
        if skipped_count > 0:
             return json.dumps({
                'message': f'Queued {len(exec_ids)} cells. Skipped {skipped_count} tagged cells.',
                'executions': exec_ids,
                'skipped_count': skipped_count
            }, indent=2)
        
        if queue_full_count > 0:
            return json.dumps({
                'status': 'partial',
                'message': f'Queue became full. Queued {len(exec_ids)} cells before hitting limit.',
                'executions': exec_ids,
                'queue_full': True,
                'retry_after_seconds': 5
            }, indent=2)
        
        return json.dumps({
            'message': f'Queued {len(exec_ids)} cells for execution',
            'executions': exec_ids
        }, indent=2)

    @mcp.tool()
    @validated_tool(CancelExecutionArgs)
    async def cancel_execution(notebook_path: str, task_id: str):
        """
        [PHASE 3.5] Gracefully cancel a running or queued execution.
        
        Sends SIGTERM to the kernel and marks the execution as cancelled.
        Unlike interrupt_kernel, this only targets a specific execution.
        """
        result = await session_manager.cancel_execution(notebook_path, task_id)
        return json.dumps(result, indent=2)

    @mcp.tool()
    @validated_tool(SubmitInputArgs)
    async def submit_input(notebook_path: str, text: str):
        """
        [Interact] Submit text to a pending input() request.
        Use this when you receive a 'notebook/input_request' notification.
        """
        try:
            await session_manager.submit_input(notebook_path, text)
            return json.dumps({"status": "sent", "text_length": len(text)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    @mcp.tool()
    def set_stop_on_error(notebook_path: str, enabled: bool):
        """
        Sets the stop_on_error flag for the session.
        When enabled, batch execution stops on first error.
        """
        result = session_manager.set_stop_on_error(notebook_path, enabled)
        return json.dumps(result)
