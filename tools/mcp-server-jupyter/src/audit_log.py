"""
Phase 5.1: Structured Audit Log

Provides structured logging for all tool executions with trace_id propagation
and performance metrics. Enables production debugging and monitoring.

Key Features:
- Structured JSON log format
- trace_id propagation through async operations
- Duration tracking for performance analysis
- Status tracking (success/error)
- Metadata capture (kernel_id, output_size, etc.)

References:
- Structured Logging: https://www.structlog.org/
- OpenTelemetry: https://opentelemetry.io/
"""

import time
import uuid
import json
from typing import Any, Dict, Optional, Callable
from functools import wraps
from contextvars import ContextVar
from loguru import logger

# Context variable for trace_id propagation across async calls
trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


class AuditLogger:
    """
    Structured audit logger for tool executions.

    Logs every tool call with:
    - Event type
    - Tool name
    - trace_id (propagates through async calls)
    - Duration (milliseconds)
    - Status (success/error)
    - Metadata (custom fields per tool)
    """

    def __init__(self, log_volume_limit_mb: float = 1.0):
        """
        Initialize audit logger.

        Args:
            log_volume_limit_mb: Max log volume per hour (MB). Default 1MB.
        """
        self.log_volume_limit_mb = log_volume_limit_mb
        self.bytes_logged = 0
        self.hour_start = time.time()
        self.sample_counter = 0  # For sampling when over limit

    def _check_volume_limit(self, log_size: int) -> bool:
        """
        Check if we're within volume limits.

        Returns:
            True if log should be written, False if it should be dropped (over limit)
        """
        current_time = time.time()

        # Reset counter every hour
        if current_time - self.hour_start > 3600:
            self.bytes_logged = 0
            self.hour_start = current_time
            self.sample_counter = 0

        limit_bytes = self.log_volume_limit_mb * 1024 * 1024

        # Hard cap: Drop logs when limit exceeded (IIRB Advisory)
        if self.bytes_logged > limit_bytes:
            # Sample 1 in 100 logs when over limit
            self.sample_counter += 1
            if self.sample_counter % 100 != 0:
                return False  # Drop this log

            # Log warning on first sample
            if self.sample_counter == 100:
                logger.warning(
                    f"Log volume exceeded {self.log_volume_limit_mb}MB/hour limit. "
                    f"Sampling 1 in 100 logs. Current: {self.bytes_logged / 1024 / 1024:.2f}MB"
                )

        self.bytes_logged += log_size
        return True  # Write this log

    def log_tool_execution(
        self,
        tool: str,
        status: str,
        duration_ms: float,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Log a tool execution event.

        Args:
            tool: Tool name (e.g., "run_cell_async")
            status: Execution status ("success", "error", "timeout")
            duration_ms: Execution duration in milliseconds
            trace_id: Optional trace ID for correlation
            metadata: Optional metadata dict (kernel_id, output_size, etc.)
        """
        # Use trace_id from context if not provided
        if trace_id is None:
            trace_id = trace_id_var.get()

        # Build log event
        event = {
            "event": "tool_execution",
            "tool": tool,
            "trace_id": trace_id or "unknown",
            "duration_ms": round(duration_ms, 2),
            "status": status,
            "timestamp": time.time(),
        }

        if metadata:
            event["metadata"] = metadata

        # Serialize to JSON
        log_json = json.dumps(event)
        log_size = len(log_json.encode("utf-8"))

        # [IIRB P0 FIX #2] NEVER drop error logs (compliance requirement)
        # Check volume limit only for success logs
        is_error = status in ["error", "timeout"]
        if not is_error and not self._check_volume_limit(log_size):
            return  # Log dropped due to volume limit (success logs only)

        # Always count error logs toward volume limit (but never drop them)
        if is_error:
            self.bytes_logged += log_size

        # Log with appropriate level
        if status == "error":
            logger.error(f"AUDIT: {log_json}")
        elif status == "timeout":
            logger.warning(f"AUDIT: {log_json}")
        else:
            logger.info(f"AUDIT: {log_json}")

    def log_kernel_event(
        self,
        event_type: str,
        kernel_id: str,
        status: str,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Log a kernel lifecycle event.

        Args:
            event_type: Event type ("start", "stop", "restart", "interrupt")
            kernel_id: Kernel identifier
            status: Event status ("success", "error")
            trace_id: Optional trace ID
            metadata: Optional metadata
        """
        event = {
            "event": "kernel_lifecycle",
            "event_type": event_type,
            "kernel_id": kernel_id,
            "status": status,
            "trace_id": trace_id or trace_id_var.get() or "unknown",
            "timestamp": time.time(),
        }

        if metadata:
            event["metadata"] = metadata

        log_json = json.dumps(event)
        log_size = len(log_json.encode("utf-8"))

        # [IIRB P0 FIX #2] NEVER drop error logs (compliance requirement)
        is_error = status == "error"
        if not is_error and not self._check_volume_limit(log_size):
            return  # Log dropped due to volume limit (success logs only)

        # Always count error logs toward volume limit (but never drop them)
        if is_error:
            self.bytes_logged += log_size

        if status == "error":
            logger.error(f"AUDIT: {log_json}")
        else:
            logger.info(f"AUDIT: {log_json}")


# Global audit logger instance
audit_logger = AuditLogger()


def audit_tool(func: Callable) -> Callable:
    """
    Decorator for auditing tool executions.

    Automatically logs:
    - Tool name (from function name)
    - Execution duration
    - Success/error status
    - trace_id (from context or generated)

    Usage:
        @audit_tool
        async def run_cell_async(...):
            pass
    """

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        # Generate or get trace_id
        trace_id = trace_id_var.get()
        if trace_id is None:
            trace_id = str(uuid.uuid4())[:8]
            trace_id_var.set(trace_id)

        # Extract metadata from kwargs
        metadata = {}
        if "kernel_id" in kwargs:
            metadata["kernel_id"] = kwargs["kernel_id"]
        if "cell_index" in kwargs:
            metadata["cell_index"] = kwargs["cell_index"]
        if "notebook_path" in kwargs:
            metadata["notebook_path"] = kwargs["notebook_path"]

        # Execute and time
        start_time = time.time()
        status = "success"

        try:
            result = await func(*args, **kwargs)

            # Capture output size if available
            if hasattr(result, "__len__"):
                try:
                    result_str = str(result)
                    metadata["output_size_bytes"] = len(result_str.encode("utf-8"))
                except Exception:
                    pass

            return result

        except Exception as e:
            status = "error"
            metadata["error_type"] = type(e).__name__
            metadata["error_message"] = str(e)[:200]  # Truncate long errors
            raise

        finally:
            duration_ms = (time.time() - start_time) * 1000

            # Log the execution
            audit_logger.log_tool_execution(
                tool=func.__name__,
                status=status,
                duration_ms=duration_ms,
                trace_id=trace_id,
                metadata=metadata,
            )

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        # Generate or get trace_id
        trace_id = trace_id_var.get()
        if trace_id is None:
            trace_id = str(uuid.uuid4())[:8]
            trace_id_var.set(trace_id)

        # Extract metadata
        metadata = {}
        if "kernel_id" in kwargs:
            metadata["kernel_id"] = kwargs["kernel_id"]

        # Execute and time
        start_time = time.time()
        status = "success"

        try:
            result = func(*args, **kwargs)
            return result

        except Exception as e:
            status = "error"
            metadata["error_type"] = type(e).__name__
            metadata["error_message"] = str(e)[:200]
            raise

        finally:
            duration_ms = (time.time() - start_time) * 1000

            audit_logger.log_tool_execution(
                tool=func.__name__,
                status=status,
                duration_ms=duration_ms,
                trace_id=trace_id,
                metadata=metadata,
            )

    # Return appropriate wrapper
    import asyncio

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def set_trace_id(trace_id: str):
    """Set trace_id in context for current execution."""
    trace_id_var.set(trace_id)


def get_trace_id() -> Optional[str]:
    """Get trace_id from context."""
    return trace_id_var.get()


def generate_trace_id() -> str:
    """Generate a new trace_id."""
    return str(uuid.uuid4())[:8]
