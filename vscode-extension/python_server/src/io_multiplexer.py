"""
I/O Multiplexer
===============

Phase 2.3 Refactoring: Extract I/O message routing from SessionManager.

This module handles:
- ZMQ IOPub message reception and routing
- Message parsing and state updates
- Output broadcasting to WebSocket connections
- Stdin (input()) request handling
- Circuit breaker for listener errors

Design Goals:
1. < 250 lines (focused responsibility)
2. No kernel process management (that's KernelLifecycle's job)
3. No execution scheduling (that's ExecutionScheduler's job)
4. Testable in isolation
"""

import asyncio
import nbformat
from typing import Dict, Any, Optional, Callable
import structlog

logger = structlog.get_logger(__name__)


class IOMultiplexer:
    """
    Manages I/O message routing between Jupyter kernel and clients.
    
    Routes ZMQ IOPub messages to appropriate execution handlers,
    broadcasts output to WebSocket connections, and handles stdin requests.
    """
    
    def __init__(self, input_request_timeout: int = 60):
        """
        Initialize the I/O multiplexer.
        
        Args:
            input_request_timeout: Timeout for input() requests in seconds
        """
        self.input_request_timeout = input_request_timeout
        logger.info(f"IOMultiplexer initialized (input_timeout={input_request_timeout}s)")
    
    async def listen_iopub(
        self,
        nb_path: str,
        kc,
        executions: Dict[str, Any],
        session_data: Dict[str, Any],
        finalize_callback: Optional[Callable] = None,
        broadcast_callback: Optional[Callable] = None,
        notification_callback: Optional[Callable] = None
    ):
        """
        Listen for IOPub messages from the kernel and route them.
        
        Args:
            nb_path: Notebook path
            kc: Jupyter kernel client
            executions: Dict mapping msg_id -> execution data
            session_data: Session state dict
            finalize_callback: Async callback to finalize execution
            broadcast_callback: Async callback to broadcast output
            notification_callback: Async callback to send MCP notifications
        """
        logger.info(f"Starting IOPub listener for {nb_path}")
        consecutive_errors = 0
        
        try:
            while True:
                try:
                    # Retrieve message from IOPub channel
                    msg = await kc.get_iopub_msg()
                    
                    # Route message to execution
                    await self._route_message(
                        nb_path=nb_path,
                        msg=msg,
                        executions=executions,
                        session_data=session_data,
                        finalize_callback=finalize_callback,
                        broadcast_callback=broadcast_callback,
                        notification_callback=notification_callback
                    )
                    
                    # Reset error counter on success
                    consecutive_errors = 0
                
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    # Circuit breaker: prevent CPU spin on errors
                    consecutive_errors += 1
                    logger.error(
                        f"Listener error for {nb_path}: {e} "
                        f"(consecutive errors: {consecutive_errors})"
                    )
                    
                    if consecutive_errors >= 5:
                        logger.critical(
                            f"[CIRCUIT BREAKER] Listener for {nb_path} hit 5 consecutive errors. "
                            f"Exiting to prevent resource exhaustion."
                        )
                        session_data['listener_healthy'] = False
                        break
                    else:
                        # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                        backoff_seconds = min(2 ** (consecutive_errors - 1), 16)
                        logger.warning(
                            f"[CIRCUIT BREAKER] Backing off for {backoff_seconds}s before retry"
                        )
                        await asyncio.sleep(backoff_seconds)
        
        except asyncio.CancelledError:
            logger.info(f"IOPub listener cancelled for {nb_path}")
    
    async def _route_message(
        self,
        nb_path: str,
        msg: Dict[str, Any],
        executions: Dict[str, Any],
        session_data: Dict[str, Any],
        finalize_callback: Optional[Callable],
        broadcast_callback: Optional[Callable],
        notification_callback: Optional[Callable]
    ):
        """
        Route a single IOPub message to the appropriate handler.
        
        Args:
            nb_path: Notebook path
            msg: ZMQ message dict
            executions: Dict of active executions
            session_data: Session state
            finalize_callback: Callback to finalize execution
            broadcast_callback: Callback to broadcast output
            notification_callback: Callback to send notifications
        """
        # Identify which execution this belongs to
        parent_id = msg['parent_header'].get('msg_id')
        if not parent_id or parent_id not in executions:
            # Message from previous run or system status - ignore
            return
        
        exec_data = executions[parent_id]
        msg_type = msg['msg_type']
        content = msg['content']
        
        # Route by message type
        if msg_type == 'status':
            await self._handle_status(
                nb_path, exec_data, content, session_data,
                finalize_callback, notification_callback
            )
        elif msg_type == 'clear_output':
            self._handle_clear_output(exec_data, content)
        elif msg_type in ['stream', 'display_data', 'execute_result', 'error']:
            await self._handle_output(
                nb_path, exec_data, msg_type, content,
                broadcast_callback, notification_callback
            )
    
    async def _handle_status(
        self,
        nb_path: str,
        exec_data: Dict[str, Any],
        content: Dict[str, Any],
        session_data: Dict[str, Any],
        finalize_callback: Optional[Callable],
        notification_callback: Optional[Callable]
    ):
        """Handle 'status' messages (kernel state changes)."""
        exec_data['kernel_state'] = content['execution_state']
        
        if content['execution_state'] == 'idle':
            # Execution completed
            if exec_data['status'] not in ['error', 'cancelled']:
                exec_data['status'] = 'completed'
            
            # Wait for finalization event (synchronizes with queue processor)
            if 'finalization_event' in exec_data:
                await exec_data['finalization_event'].wait()
            
            # Finalize: Save to disk
            if finalize_callback:
                try:
                    await finalize_callback(nb_path, exec_data)
                except Exception as e:
                    logger.warning(f"Finalize execution failed: {e}")
            
            # Track successful execution
            if session_data and exec_data.get('cell_index') is not None:
                session_data.setdefault('executed_indices', set()).add(
                    exec_data['cell_index']
                )
            
            # Send completion notification
            if notification_callback:
                try:
                    await notification_callback("notebook/status", {
                        "notebook_path": nb_path,
                        "exec_id": exec_data.get('id'),
                        "status": exec_data['status']
                    })
                except Exception as e:
                    logger.warning(f"Failed to send status notification: {e}")
    
    def _handle_clear_output(self, exec_data: Dict[str, Any], content: Dict[str, Any]):
        """Handle 'clear_output' messages (for progress bars)."""
        wait = content.get('wait', False)
        if not wait:
            # Immediate clear: reset outputs but keep metadata
            exec_data['outputs'] = []
            # Note: output_count is NOT reset - agents track cumulative index
    
    async def _handle_output(
        self,
        nb_path: str,
        exec_data: Dict[str, Any],
        msg_type: str,
        content: Dict[str, Any],
        broadcast_callback: Optional[Callable],
        notification_callback: Optional[Callable]
    ):
        """Handle output messages (stream, display_data, execute_result, error)."""
        # Convert to nbformat output
        output = self._create_output(msg_type, content, exec_data)
        
        if output:
            # Broadcast to WebSocket clients
            if broadcast_callback:
                await broadcast_callback({
                    "jsonrpc": "2.0",
                    "method": "notebook/output",
                    "params": {
                        "notebook_path": nb_path,
                        "task_id": exec_data.get('id'),
                        "cell_index": exec_data.get('cell_index'),
                        "output": output,
                    }
                })
            
            # Append to execution outputs
            exec_data['outputs'].append(output)
            exec_data['output_count'] = len(exec_data['outputs'])
            exec_data['last_activity'] = asyncio.get_event_loop().time()
            
            # Send MCP notification
            if notification_callback:
                try:
                    await notification_callback("notebook/output", {
                        "notebook_path": nb_path,
                        "exec_id": exec_data.get('id'),
                        "type": msg_type,
                        "content": content
                    })
                except Exception as e:
                    logger.warning(f"Failed to send MCP notification: {e}")
    
    def _create_output(
        self,
        msg_type: str,
        content: Dict[str, Any],
        exec_data: Dict[str, Any]
    ) -> Optional[Any]:
        """
        Create nbformat output from message content.
        
        Args:
            msg_type: Type of message (stream, display_data, etc.)
            content: Message content dict
            exec_data: Execution data dict (for execution_count)
        
        Returns:
            nbformat output object or None
        """
        if msg_type == 'stream':
            return nbformat.v4.new_output(
                'stream',
                name=content['name'],
                text=content['text']
            )
        elif msg_type == 'display_data':
            return nbformat.v4.new_output(
                'display_data',
                data=content['data'],
                metadata=content['metadata']
            )
        elif msg_type == 'execute_result':
            exec_data['execution_count'] = content.get('execution_count')
            return nbformat.v4.new_output(
                'execute_result',
                data=content['data'],
                metadata=content['metadata'],
                execution_count=content.get('execution_count')
            )
        elif msg_type == 'error':
            exec_data['status'] = 'error'
            return nbformat.v4.new_output(
                'error',
                ename=content['ename'],
                evalue=content['evalue'],
                traceback=content['traceback']
            )
        
        return None
    
    async def listen_stdin(
        self,
        nb_path: str,
        kc,
        session_data: Dict[str, Any],
        notification_callback: Optional[Callable] = None,
        interrupt_callback: Optional[Callable] = None
    ):
        """
        Listen for stdin (input()) requests from the kernel.
        
        Args:
            nb_path: Notebook path
            kc: Jupyter kernel client
            session_data: Session state dict
            notification_callback: Callback to send input request notifications
            interrupt_callback: Callback to interrupt kernel on timeout
        """
        logger.info(f"Starting stdin listener for {nb_path}")
        
        try:
            while True:
                # Wait for stdin message
                try:
                    if not kc.stdin_channel.is_alive():
                        await asyncio.sleep(0.5)
                        continue
                    
                    if await kc.stdin_channel.msg_ready():
                        msg = await kc.stdin_channel.get_msg(timeout=0)
                    else:
                        await asyncio.sleep(0.1)
                        continue
                
                except Exception:
                    await asyncio.sleep(0.1)
                    continue
                
                msg_type = msg['header']['msg_type']
                content = msg['content']
                
                if msg_type == 'input_request':
                    await self._handle_input_request(
                        nb_path, kc, content, session_data,
                        notification_callback, interrupt_callback
                    )
        
        except asyncio.CancelledError:
            logger.info(f"Stdin listener cancelled for {nb_path}")
        except Exception as e:
            logger.error(f"Stdin listener error for {nb_path}: {e}")
    
    async def _handle_input_request(
        self,
        nb_path: str,
        kc,
        content: Dict[str, Any],
        session_data: Dict[str, Any],
        notification_callback: Optional[Callable],
        interrupt_callback: Optional[Callable]
    ):
        """Handle input() request from kernel."""
        logger.info(f"Kernel requested input: {content.get('prompt', '')}")
        
        # Notify client to ask user
        if notification_callback:
            await notification_callback("notebook/input_request", {
                "notebook_path": nb_path,
                "prompt": content.get('prompt', ''),
                "password": content.get('password', False)
            })
        
        # Wait for input with timeout watchdog
        session_data['waiting_for_input'] = True
        try:
            timeout = session_data.get(
                'input_request_timeout',
                self.input_request_timeout
            )
            elapsed = 0.0
            interval = 0.1
            timed_out = True
            
            while elapsed < timeout:
                await asyncio.sleep(interval)
                elapsed += interval
                if not session_data.get('waiting_for_input'):
                    timed_out = False
                    break
            
            if timed_out:
                logger.warning(
                    f"Input request timed out for {nb_path} after {timeout}s. "
                    f"Attempting to recover."
                )
                # Send empty input to unblock kernel
                try:
                    kc.input('')
                    logger.info("Sent empty string to kernel to clear input request")
                except Exception as e:
                    logger.warning(
                        f"Failed to send empty input: {e}. "
                        f"Sending interrupt as fallback."
                    )
                    if interrupt_callback:
                        await interrupt_callback(nb_path)
        finally:
            session_data['waiting_for_input'] = False
