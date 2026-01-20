"""
Execution Scheduler
===================

Phase 2.2 Refactoring: Extract execution scheduling from SessionManager.

This module handles:
- Queue processing (asyncio.Queue operations)
- Execution ordering and linearity warnings
- Timeout management
- stop_on_error logic
- Audit logging for execution lifecycle

Design Goals:
1. < 250 lines (focused responsibility)
2. No I/O multiplexing (that's IOMultiplexer's job)
3. No kernel process management (that's KernelLifecycle's job)
4. Testable in isolation
"""

import asyncio
import hashlib
import time
from typing import Dict, Any, Optional, Callable, Awaitable
import structlog

logger = structlog.get_logger(__name__)


class ExecutionScheduler:
    """
    Manages execution queue processing and scheduling for notebook sessions.
    
    Ensures cells execute sequentially (one at a time per notebook),
    handles timeouts, and implements stop_on_error logic.
    """
    
    def __init__(self, default_timeout: int = 300):
        """
        Initialize the execution scheduler.
        
        Args:
            default_timeout: Default execution timeout in seconds (default: 300)
        """
        self.default_timeout = default_timeout
        logger.info(f"ExecutionScheduler initialized (default_timeout={default_timeout}s)")
    
    async def process_queue(
        self,
        nb_path: str,
        session_data: Dict[str, Any],
        execute_callback: Callable[[str], Awaitable[str]]
    ):
        """
        Background loop that processes execution requests from the queue.
        
        Args:
            nb_path: Absolute path to the notebook
            session_data: Session dictionary containing queue and state
            execute_callback: Async function to execute code: (code: str) -> msg_id: str
        
        Expected session_data keys:
            - execution_queue: asyncio.Queue
            - queued_executions: Dict[exec_id, Dict]
            - executions: Dict[msg_id, Dict]
            - execution_counter: int
            - max_executed_index: int (optional)
            - stop_on_error: bool (optional)
            - execution_timeout: int (optional)
        """
        logger.info(f"Starting queue processor for {nb_path}")
        
        try:
            while True:
                # Get next execution request from queue
                exec_request = await session_data['execution_queue'].get()
                
                # Check for shutdown signal
                if exec_request is None:
                    logger.info(f"Queue processor shutting down for {nb_path}")
                    break
                
                cell_index = exec_request['cell_index']
                code = exec_request['code']
                exec_id = exec_request['exec_id']
                
                # Remove from queued executions (now processing)
                if exec_id in session_data['queued_executions']:
                    del session_data['queued_executions'][exec_id]
                
                try:
                    await self._execute_cell(
                        nb_path=nb_path,
                        session_data=session_data,
                        cell_index=cell_index,
                        code=code,
                        exec_id=exec_id,
                        execute_callback=execute_callback
                    )
                finally:
                    # Mark task as done
                    session_data['execution_queue'].task_done()
        
        except asyncio.CancelledError:
            logger.info(f"Queue processor cancelled for {nb_path}")
        except Exception as e:
            logger.error(f"Queue processor error for {nb_path}: {e}")
    
    async def _execute_cell(
        self,
        nb_path: str,
        session_data: Dict[str, Any],
        cell_index: int,
        code: str,
        exec_id: str,
        execute_callback: Callable[[str], Awaitable[str]]
    ):
        """
        Execute a single cell with timeout and error handling.
        
        Args:
            nb_path: Absolute path to the notebook
            session_data: Session dictionary
            cell_index: Cell index being executed
            code: Code to execute
            exec_id: Execution ID (UUID)
            execute_callback: Function to execute code
        """
        # [SCIENTIFIC INTEGRITY] Check Linearity
        linearity_warning = self._check_linearity(session_data, cell_index)
        
        # Update wavefront (track highest executed index)
        current_index = cell_index
        max_idx = session_data.get('max_executed_index', -1)
        if current_index > max_idx:
            session_data['max_executed_index'] = current_index
        
        try:
            # Increment execution counter
            session_data['execution_counter'] += 1
            expected_count = session_data['execution_counter']
            
            # [AUDIT] Log execution start
            code_hash = hashlib.sha256(code.encode('utf-8')).hexdigest()[:16]
            start_timestamp = time.time()
            
            logger.info(
                "[AUDIT] execution_started",
                notebook_path=nb_path,
                cell_index=cell_index,
                exec_id=exec_id,
                code_hash=code_hash,
                code_length=len(code),
                execution_count=expected_count,
            )
            
            # Execute the cell via callback (delegates to SessionManager/KernelLifecycle)
            msg_id = await execute_callback(code)
            
            # Register execution metadata
            session_data['executions'][msg_id] = {
                'id': exec_id,
                'cell_index': cell_index,
                'status': 'running',
                'outputs': [],
                'execution_count': expected_count,
                'text_summary': linearity_warning,
                'kernel_state': 'busy',
                'start_time': asyncio.get_event_loop().time(),
                'output_count': 0,
                'last_activity': asyncio.get_event_loop().time(),
                'finalization_event': asyncio.Event(),
            }
            
            # Wait for execution to complete with timeout
            await self._wait_for_completion(
                nb_path=nb_path,
                session_data=session_data,
                msg_id=msg_id,
                exec_id=exec_id,
                cell_index=cell_index,
                code_hash=code_hash,
                start_timestamp=start_timestamp
            )
        
        except Exception as e:
            logger.error(f"Error executing cell {cell_index} in {nb_path}: {e}")
            # Mark execution as failed
            if exec_id:
                for msg_id, data in session_data['executions'].items():
                    if data.get('id') == exec_id:
                        data['status'] = 'error'
                        data['error'] = str(e)
                        break
            
            # If stop_on_error, clear remaining queue
            if session_data.get('stop_on_error', False):
                await self._clear_queue_on_error(session_data, "exception during execution")
    
    def _check_linearity(self, session_data: Dict[str, Any], cell_index: int) -> str:
        """
        Check if cell execution is linear (top-to-bottom order).
        
        Returns warning message if executing out of order.
        """
        current_index = cell_index
        max_idx = session_data.get('max_executed_index', -1)
        
        if current_index >= 0 and current_index < max_idx:
            # Agent is executing out of order
            return (
                f"\n\n⚠️  [INTEGRITY WARNING] You are executing Cell {current_index + 1} "
                f"after Cell {max_idx + 1}. This creates hidden state. "
                f"The notebook state in memory (Cell {current_index + 1} v2 + later cells v1) "
                f"cannot be reproduced by running 'Run All' from top to bottom. "
                f"Recommend re-running subsequent cells to ensure reproducibility.\n"
            )
        
        return ""
    
    async def _wait_for_completion(
        self,
        nb_path: str,
        session_data: Dict[str, Any],
        msg_id: str,
        exec_id: str,
        cell_index: int,
        code_hash: str,
        start_timestamp: float
    ):
        """
        Wait for cell execution to complete with timeout handling.
        
        Args:
            nb_path: Notebook path
            session_data: Session dictionary
            msg_id: Jupyter message ID
            exec_id: Execution ID (UUID)
            cell_index: Cell index
            code_hash: SHA-256 hash of code (first 16 chars)
            start_timestamp: Execution start time (seconds since epoch)
        """
        # Use per-session timeout or default
        session_timeout = session_data.get('execution_timeout', self.default_timeout)
        timeout_remaining = session_timeout
        
        while timeout_remaining > 0:
            await asyncio.sleep(0.5)
            timeout_remaining -= 0.5
            
            exec_data = session_data['executions'].get(msg_id)
            if exec_data and exec_data['status'] in ['completed', 'error', 'cancelled']:
                # [AUDIT] Log completion
                duration_ms = (time.time() - start_timestamp) * 1000
                logger.info(
                    "[AUDIT] execution_finished",
                    notebook_path=nb_path,
                    exec_id=exec_id,
                    cell_index=cell_index,
                    code_hash=code_hash,
                    exit_status=exec_data['status'],
                    duration_ms=round(duration_ms, 2),
                    output_count=exec_data.get('output_count', 0)
                )
                
                # Check if we should stop on error
                if exec_data['status'] == 'error' and session_data.get('stop_on_error', False):
                    await self._clear_queue_on_error(
                        session_data,
                        f"error in cell {cell_index}"
                    )
                
                # Signal that finalization can proceed
                exec_data['finalization_event'].set()
                return  # Exit successfully
        
        # Timeout occurred
        exec_data = session_data['executions'].get(msg_id)
        if exec_data:
            exec_data['finalization_event'].set()
        
        logger.warning(f"Execution timed out for cell {cell_index} in {nb_path}")
        if msg_id in session_data['executions']:
            session_data['executions'][msg_id]['status'] = 'timeout'
            session_data['executions'][msg_id]['error'] = f"Execution exceeded {session_timeout}s timeout"
        
        # If stop_on_error, also stop on timeout
        if session_data.get('stop_on_error', False):
            await self._clear_queue_on_error(
                session_data,
                f"timeout in cell {cell_index}"
            )
    
    async def _clear_queue_on_error(self, session_data: Dict[str, Any], reason: str):
        """
        Clear remaining items in execution queue when stop_on_error is True.
        
        Args:
            session_data: Session dictionary
            reason: Reason for clearing queue (for logging)
        """
        logger.warning(f"Clearing remaining queue ({reason}, stop_on_error=True)")
        
        while not session_data['execution_queue'].empty():
            try:
                cancelled_request = session_data['execution_queue'].get_nowait()
                if cancelled_request is not None:
                    # Mark associated execution as cancelled
                    cancelled_id = cancelled_request['exec_id']
                    for msg_id_cancel, data_cancel in session_data['executions'].items():
                        if data_cancel.get('id') == cancelled_id:
                            data_cancel['status'] = 'cancelled'
                            data_cancel['error'] = f"Cancelled due to {reason}"
                            break
                    session_data['execution_queue'].task_done()
            except asyncio.QueueEmpty:
                break
