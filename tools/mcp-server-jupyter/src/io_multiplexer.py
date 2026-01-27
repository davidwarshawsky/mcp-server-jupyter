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

[NETWORK FIX] Ring buffer instead of time-based TTL for orphaned messages:
- Old: Drop messages after 5 seconds (race condition in high-latency networks)
- New: Keep up to 1000 orphaned messages in memory; drop oldest if size exceeded
- This allows clients with slow registration to still receive outputs
"""

import asyncio
from collections import deque
from typing import Dict, Any, Optional, Callable
import structlog
import nbformat

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
        logger.info(
            f"IOMultiplexer initialized (input_timeout={input_request_timeout}s)"
        )
        # [NETWORK FIX] Ring buffer for orphaned messages (size-bounded, not time-based)
        # Stores up to 1000 orphaned messages per parent_id
        # Older messages are dropped when limit is exceeded
        self._message_buffer = {}  # Dict[parent_id] -> deque of messages
        self._max_orphaned_per_id = 1000

    async def listen_iopub(
        self,
        nb_path: str,
        kc,
        executions: Dict[str, Any],
        session_data: Dict[str, Any],
        finalize_callback: Optional[Callable] = None,
        broadcast_callback: Optional[Callable] = None,
        notification_callback: Optional[Callable] = None,
        persist_callback: Optional[Callable] = None,
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
            persist_callback: Async callback to persist session state after cell execution
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
                        notification_callback=notification_callback,
                        persist_callback=persist_callback,
                    )

                    # Reset error counter on success
                    consecutive_errors = 0

                    # After processing a live message, attempt to flush any
                    # buffered messages whose parent_id has since been
                    # registered in `executions`.
                    try:
                        await self._flush_buffered_messages(
                            executions, session_data, finalize_callback, broadcast_callback, notification_callback, persist_callback
                        )
                    except Exception:
                        # Best-effort: do not let buffer flushing break the listener
                        pass

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
                        session_data["listener_healthy"] = False
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
        notification_callback: Optional[Callable],
        persist_callback: Optional[Callable] = None,
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
            persist_callback: Callback to persist session state
        """
        # Identify which execution this belongs to
        parent_id = msg.get("parent_header", {}).get("msg_id")

        # Quick fuzzy-match: Sometimes kernels send slightly different msg_id suffixes
        # (e.g. ..._4 vs ..._6). Try to match based on base prefix to avoid buffering
        # messages unnecessarily when an execution key is present with same base.
        if parent_id and executions and parent_id not in executions:
            try:
                base = parent_id.rsplit("_", 1)[0]
                for k in executions.keys():
                    if k.startswith(base) or k.rsplit("_", 1)[0] == base:
                        # Rewrite parent_id to the matched key and continue processing
                        logger.debug(
                            f"Fuzzy-matched IOPub parent_id {parent_id} -> {k}"
                        )
                        parent_id = k
                        break
            except Exception:
                pass

        if not parent_id or parent_id not in executions:
            # [NETWORK FIX] Buffer with ring buffer (size-bounded, not time-based)
            # If the client is slow to register, we wait up to 1000 messages
            # If buffer overflows, we drop the oldest message
            try:
                exec_keys = list(executions.keys()) if executions is not None else []
                logger.debug(
                    f"Buffering IOPub msg (type={msg.get('msg_type')} parent_id={parent_id}) - known exec keys: {exec_keys[:5]} (len={len(exec_keys)})"
                )
                # Store nb_path in msg to preserve context for later routing
                msg_with_context = dict(msg)
                msg_with_context["_nb_path"] = nb_path
                
                # Ring buffer: store (timestamp, message) in deque with max size
                if parent_id not in self._message_buffer:
                    self._message_buffer[parent_id] = deque(maxlen=self._max_orphaned_per_id)

                timestamp = asyncio.get_event_loop().time()
                self._message_buffer[parent_id].append((timestamp, msg_with_context))
            except Exception:
                pass
            return

        # If we reach here, parent_id exists and we should also ensure any
        # buffered messages for this parent are processed as well. This helps
        # with races where some messages arrived before registration.
        if parent_id in getattr(self, "_message_buffer", {}):
            buffered_deque = self._message_buffer.pop(parent_id, deque())
            for _, buffered_msg in buffered_deque:
                try:
                    # Process buffered messages by routing them through
                    # the same code path (avoid recursion loops by calling
                    # the internal handlers directly where possible).
                    await self._route_message(
                        nb_path=nb_path,
                        msg=buffered_msg,
                        executions=executions,
                        session_data=session_data,
                        finalize_callback=finalize_callback,
                        broadcast_callback=broadcast_callback,
                        notification_callback=notification_callback,
                        persist_callback=persist_callback,
                    )
                except Exception:
                    # Ignore buffered processing errors
                    pass

        exec_data = executions[parent_id]
        msg_type = msg["msg_type"]
        content = msg["content"]

        # Route by message type
        if msg_type == "status":
            await self._handle_status(
                parent_id,
                nb_path,
                exec_data,
                content,
                session_data,
                finalize_callback,
                notification_callback,
                persist_callback,
            )
        elif msg_type == "clear_output":
            self._handle_clear_output(exec_data, content)
        elif msg_type in ["stream", "display_data", "execute_result", "error"]:
            await self._handle_output(
                nb_path,
                exec_data,
                msg_type,
                content,
                broadcast_callback,
                notification_callback,
            )
            # [OBSERVABILITY FIX] Signal completion event if execution is complete
            if msg_type == "status" and content.get("execution_state") == "idle":
                if "completion_event" in exec_data:
                    exec_data["completion_event"].set()

    async def _handle_status(
        self,
        parent_id: str,
        nb_path: str,
        exec_data: Dict[str, Any],
        content: Dict[str, Any],
        session_data: Dict[str, Any],
        finalize_callback: Optional[Callable],
        notification_callback: Optional[Callable],
        persist_callback: Optional[Callable] = None,
    ):
        """Handle 'status' messages (kernel state changes)."""
        exec_data["kernel_state"] = content["execution_state"]

        if content["execution_state"] == "idle":
            # Execution completed
            if exec_data["status"] not in ["error", "cancelled"]:
                exec_data["status"] = "completed"

            # [OBSERVABILITY FIX] Signal completion event so waiting coroutine wakes up
            if "completion_event" in exec_data:
                exec_data["completion_event"].set()

            # Before finalizing, check if there are any buffered messages for this parent
            # that arrived before the execution was registered. Process them now to ensure
            # they are included in the finalization step.
            try:
                # Exact match for any buffered messages
                if parent_id in getattr(self, "_message_buffer", {}):
                    entries = self._message_buffer.pop(parent_id, deque())
                    for _, buffered_msg in entries:
                        try:
                            nb_path_from_msg = buffered_msg.pop("_nb_path", "")
                            await self._route_message(
                                nb_path=nb_path_from_msg,
                                msg=buffered_msg,
                                executions={parent_id: exec_data},
                                session_data=session_data,
                                finalize_callback=finalize_callback,
                                broadcast_callback=None,
                                notification_callback=notification_callback,
                                persist_callback=persist_callback,
                            )
                        except Exception:
                            pass

                # Fuzzy prefix matches: also process buffered messages that share
                # the same base prefix (handles cases like msg_id_3 vs msg_id_5)
                try:
                    parent_base = parent_id.rsplit("_", 1)[0]
                    keys_to_check = [k for k in list(self._message_buffer.keys()) if k and k.rsplit("_", 1)[0] == parent_base]
                    for k in keys_to_check:
                        entries = self._message_buffer.pop(k, deque())
                        for _, buffered_msg in entries:
                            try:
                                nb_path_from_msg = buffered_msg.pop("_nb_path", "")
                                await self._route_message(
                                    nb_path=nb_path_from_msg,
                                    msg=buffered_msg,
                                    executions={parent_id: exec_data},
                                    session_data=session_data,
                                    finalize_callback=finalize_callback,
                                    broadcast_callback=None,
                                    notification_callback=notification_callback,
                                    persist_callback=persist_callback,
                                )
                            except Exception:
                                pass
                except Exception:
                    pass
            except Exception:
                pass

            # Wait for finalization event (synchronizes with queue processor)
            if "finalization_event" in exec_data:
                await exec_data["finalization_event"].wait()

            # Finalize: Save to disk
            if finalize_callback:
                try:
                    await finalize_callback(nb_path, exec_data)
                except Exception as e:
                    logger.warning(f"Finalize execution failed: {e}")

            # Track successful execution
            if session_data and exec_data.get("cell_index") is not None:
                session_data.setdefault("executed_indices", set()).add(
                    exec_data["cell_index"]
                )

                # [SMART SYNC FIX] Persist updated executed_indices to disk
                if persist_callback:
                    try:
                        await persist_callback(nb_path, session_data)
                    except Exception as e:
                        logger.warning(f"Failed to persist session state: {e}")

            # Send completion notification
            if notification_callback:
                try:
                    await notification_callback(
                        "notebook/status",
                        {
                            "notebook_path": nb_path,
                            "exec_id": exec_data.get("id"),
                            "status": exec_data["status"],
                        },
                    )
                except Exception as e:
                    logger.warning(f"Failed to send status notification: {e}")

    def _handle_clear_output(self, exec_data: Dict[str, Any], content: Dict[str, Any]):
        """Handle 'clear_output' messages (for progress bars)."""
        wait = content.get("wait", False)
        if not wait:
            # Immediate clear: reset outputs but keep metadata
            exec_data["outputs"] = []
            # Note: output_count is NOT reset - agents track cumulative index

    async def _handle_output(
        self,
        nb_path: str,
        exec_data: Dict[str, Any],
        msg_type: str,
        content: Dict[str, Any],
        broadcast_callback: Optional[Callable],
        notification_callback: Optional[Callable],
    ):
        """Handle output messages (stream, display_data, execute_result, error)."""
        # Convert to nbformat output
        output = self._create_output(msg_type, content, exec_data)

        if output:
            # Broadcast to WebSocket clients
            if broadcast_callback:
                await broadcast_callback(
                    {
                        "jsonrpc": "2.0",
                        "method": "notebook/output",
                        "params": {
                            "notebook_path": nb_path,
                            "task_id": exec_data.get("id"),
                            "cell_index": exec_data.get("cell_index"),
                            "output": output,
                        },
                    }
                )

            # Append to execution outputs
            exec_data["outputs"].append(output)
            exec_data["output_count"] = len(exec_data["outputs"])
            exec_data["last_activity"] = asyncio.get_event_loop().time()

            # Send MCP notification
            if notification_callback:
                try:
                    await notification_callback(
                        "notebook/output",
                        {
                            "notebook_path": nb_path,
                            "exec_id": exec_data.get("id"),
                            "type": msg_type,
                            "content": content,
                        },
                    )
                except Exception as e:
                    logger.warning(f"Failed to send MCP notification: {e}")

    def _create_output(
        self, msg_type: str, content: Dict[str, Any], exec_data: Dict[str, Any]
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
        if msg_type == "stream":
            return nbformat.v4.new_output(
                "stream", name=content["name"], text=content["text"]
            )
        elif msg_type == "display_data":
            return nbformat.v4.new_output(
                "display_data", data=content["data"], metadata=content["metadata"]
            )
        elif msg_type == "execute_result":
            exec_data["execution_count"] = content.get("execution_count")
            return nbformat.v4.new_output(
                "execute_result",
                data=content["data"],
                metadata=content["metadata"],
                execution_count=content.get("execution_count"),
            )
        elif msg_type == "error":
            exec_data["status"] = "error"
            return nbformat.v4.new_output(
                "error",
                ename=content["ename"],
                evalue=content["evalue"],
                traceback=content["traceback"],
            )

        return None

    async def _flush_buffered_messages(
        self,
        executions: Dict[str, Any],
        session_data: Dict[str, Any],
        finalize_callback: Optional[Callable],
        broadcast_callback: Optional[Callable],
        notification_callback: Optional[Callable],
        persist_callback: Optional[Callable] = None,
    ):
        """Process any buffered IOPub messages whose parent_id has been
        registered in the executions mapping. This is a best-effort helper to
        mitigate a race between IOPub arrival and execution registration.
        
        For messages that don't have matching executions but are old enough (>1 second),
        we assume they might be from a kernel system message or previous execution.
        We route them to the most recent execution as a fallback.
        """
        if not hasattr(self, "_message_buffer"):
            return

        now = asyncio.get_event_loop().time()
        # Collect keys to process and stale keys to drop
        to_process = []
        to_drop = []
        to_process_stale = {}  # parent_id -> entries for old messages without matching execution
        
        for parent_id, entries in list(self._message_buffer.items()):
            if not entries:
                continue
            
            msg_age = now - entries[0][0]
            
            # Check if parent_id is registered
            if parent_id in executions:
                to_process.append(parent_id)
            # If message is old (>1 second) and still no matching execution,
            # save for fallback routing
            elif msg_age > 1.0:
                to_process_stale[parent_id] = entries
                to_drop.append(parent_id)
            # Drop entries older than TTL without a matching execution
            elif msg_age > self._buffer_ttl:
                to_drop.append(parent_id)

        # Drop stale entries
        for key in to_drop:
            try:
                self._message_buffer.pop(key, None)
            except Exception:
                pass

        # Process messages with matching registered executions  
        for parent_id in to_process:
            entries = self._message_buffer.pop(parent_id, [])
            for _, buffered_msg in entries:
                try:
                    nb_path_from_msg = buffered_msg.pop("_nb_path", "")
                    await self._route_message(
                        nb_path=nb_path_from_msg,
                        msg=buffered_msg,
                        executions=executions,
                        session_data=session_data,
                        finalize_callback=finalize_callback,
                        broadcast_callback=broadcast_callback,
                        notification_callback=notification_callback,
                        persist_callback=persist_callback,
                    )
                except Exception:
                    # Ignore errors processing buffered messages
                    pass

        # Process stale messages: route them to a recent execution as a best-effort
        # If messages are older than 1s and no matching execution exists, we assume
        # they may belong to a just-completed or recently started execution. Route
        # them to the most recently active execution to avoid losing outputs.
        try:
            if executions:
                # Pick the best candidate: prefer running executions, then highest last_activity
                candidates = []
                for key, data in executions.items():
                    candidates.append((key, data))

                # Prefer running executions
                running = [c for c in candidates if c[1].get("status") == "running"]
                if running:
                    fallback_key, fallback_exec = running[0]
                else:
                    # Use last_activity timestamp if available, else last key
                    candidates_sorted = sorted(
                        candidates,
                        key=lambda kv: kv[1].get("last_activity", 0),
                        reverse=True,
                    )
                    fallback_key, fallback_exec = candidates_sorted[0]

                # Route each stale entry to the fallback execution
                for parent_id, entries in to_process_stale.items():
                    try:
                        for _, buffered_msg in entries:
                            try:
                                nb_path_from_msg = buffered_msg.pop("_nb_path", "")
                                # Route using a small executions mapping that maps the
                                # chosen fallback_key to the fallback_exec data
                                await self._route_message(
                                    nb_path=nb_path_from_msg,
                                    msg=buffered_msg,
                                    executions={fallback_key: fallback_exec},
                                    session_data=session_data,
                                    finalize_callback=finalize_callback,
                                    broadcast_callback=broadcast_callback,
                                    notification_callback=notification_callback,
                                    persist_callback=persist_callback,
                                )
                            except Exception:
                                pass
                    except Exception:
                        pass
        except Exception:
            # Best-effort: never allow buffered message routing to raise
            pass

    async def listen_stdin(
        self,
        nb_path: str,
        kc,
        session_data: Dict[str, Any],
        notification_callback: Optional[Callable] = None,
        interrupt_callback: Optional[Callable] = None,
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

                msg_type = msg["header"]["msg_type"]
                content = msg["content"]

                if msg_type == "input_request":
                    await self._handle_input_request(
                        nb_path,
                        kc,
                        content,
                        session_data,
                        notification_callback,
                        interrupt_callback,
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
        interrupt_callback: Optional[Callable],
    ):
        """Handle input() request from kernel."""
        logger.info(f"Kernel requested input: {content.get('prompt', '')}")

        # Notify client to ask user
        if notification_callback:
            await notification_callback(
                "notebook/input_request",
                {
                    "notebook_path": nb_path,
                    "prompt": content.get("prompt", ""),
                    "password": content.get("password", False),
                },
            )

        # Wait for input with timeout watchdog
        session_data["waiting_for_input"] = True
        try:
            timeout = session_data.get(
                "input_request_timeout", self.input_request_timeout
            )
            elapsed = 0.0
            interval = 0.1
            timed_out = True

            while elapsed < timeout:
                await asyncio.sleep(interval)
                elapsed += interval
                if not session_data.get("waiting_for_input"):
                    timed_out = False
                    break

            if timed_out:
                logger.warning(
                    f"Input request timed out for {nb_path} after {timeout}s. "
                    f"Attempting to recover."
                )
                # Send empty input to unblock kernel
                try:
                    kc.input("")
                    logger.info("Sent empty string to kernel to clear input request")
                except Exception as e:
                    logger.warning(
                        f"Failed to send empty input: {e}. "
                        f"Sending interrupt as fallback."
                    )
                    if interrupt_callback:
                        await interrupt_callback(nb_path)
        finally:
            session_data["waiting_for_input"] = False
