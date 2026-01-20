import sys
import logging
import logging.handlers
import structlog
import uuid
import contextvars
from typing import Any, Dict, Optional, List
import os
from pathlib import Path

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

# Context variables for tracing (Request ID, Session ID)
request_id_ctx = contextvars.ContextVar("request_id", default="startup")

def add_otel_trace_info(logger, method_name, event_dict):
    """
    A structlog processor to add OpenTelemetry trace and span IDs to logs.
    """
    span = trace.get_current_span()
    if span != trace.INVALID_SPAN:
        event_dict['trace_id'] = f"0x{span.get_span_context().trace_id:032x}"
        event_dict['span_id'] = f"0x{span.get_span_context().span_id:016x}"
    return event_dict

def configure_logging(level="INFO"):
    """
    Configures structured JSON logging with OpenTelemetry integration.
    """
    # --- OpenTelemetry Configuration ---
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otel_endpoint:
        resource = Resource(attributes={"service.name": "mcp-jupyter-server"})
        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=otel_endpoint))
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        print(f"[OTEL] Tracing enabled. Exporting to {otel_endpoint}", file=sys.stderr)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        add_otel_trace_info,  # Add OTEL trace info
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # If running in a TTY (dev), keep colors. If prod (pipe/file), use JSON.
    if sys.stderr.isatty():
        processors = shared_processors + [structlog.dev.ConsoleRenderer()]
    else:
        processors = shared_processors + [structlog.processors.JSONRenderer()]

    # Check if audit log file should be written
    audit_log_path = os.environ.get("MCP_AUDIT_LOG_PATH")
    
    if audit_log_path:
        # Dual logging: stderr + file for VS Code audit viewer
        audit_path = Path(audit_log_path).expanduser()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        
        # [AUDIT FIX] Use rotating file handler to prevent disk exhaustion
        # 10MB max file size, keep 3 backups (audit.log, audit.log.1, audit.log.2, audit.log.3)
        max_bytes = int(os.environ.get("MCP_AUDIT_LOG_MAX_BYTES", 10 * 1024 * 1024))  # 10MB default
        backup_count = int(os.environ.get("MCP_AUDIT_LOG_BACKUP_COUNT", 3))
        
        print(f"[AUDIT] Writing audit log to {audit_path} (max {max_bytes // (1024*1024)}MB, {backup_count} backups)", file=sys.stderr)
        
        # Wrapper to make RotatingFileHandler work with structlog's file-like interface
        class RotatingFileWrapper:
            """Wraps RotatingFileHandler to provide file-like write() interface for structlog."""
            def __init__(self, path: Path, max_bytes: int, backup_count: int):
                self._handler = logging.handlers.RotatingFileHandler(
                    str(path),
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding='utf-8'
                )
                # Open stream initially
                if self._handler.stream is None:
                    self._handler.stream = self._handler._open()
            
            def write(self, msg: str) -> None:
                """Write message, rotating if needed."""
                # Check if rotation is needed
                if self._handler.stream:
                    # Create a minimal LogRecord just for size checking
                    record = logging.makeLogRecord({"msg": msg})
                    if self._handler.shouldRollover(record):
                        self._handler.doRollover()
                    self._handler.stream.write(msg)
            
            def flush(self) -> None:
                """Flush the underlying stream."""
                if self._handler.stream:
                    self._handler.stream.flush()
        
        audit_file = RotatingFileWrapper(audit_path, max_bytes, backup_count)
        
        # Use a multi-target logger factory
        class DualLoggerFactory:
            def __init__(self, targets: List):
                self._targets = targets
            def __call__(self, *args, **kwargs):
                return DualLogger(self._targets)
        
        class DualLogger:
            def __init__(self, targets: List):
                self._targets = targets
            def msg(self, message: str) -> None:
                for target in self._targets:
                    target.write(message + "\n")
                    target.flush()
            log = debug = info = warn = warning = error = critical = exception = msg
        
        logger_factory = DualLoggerFactory([sys.stderr, audit_file])
    else:
        logger_factory = structlog.PrintLoggerFactory(file=sys.stderr)
    
    structlog.configure(
        processors=processors,
        logger_factory=logger_factory,
        cache_logger_on_first_use=True,
    )

    # Redirect standard logging to structlog
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)
    logging.getLogger().handlers = []  # Clear default handlers

    # Hook into stdlib logger
    def logger_factory(name):
        return structlog.get_logger(logger_name=name)

    return structlog.get_logger()


def get_logger(name=None):
    return structlog.get_logger(name)

def get_tracer(name=None):
    """Returns an OpenTelemetry tracer instance."""
    return trace.get_tracer(name if name else __name__)

def generate_request_id():
    req_id = str(uuid.uuid4())
    request_id_ctx.set(req_id)
    return req_id

def set_request_id(req_id: str):
    """
    [FIX #7] Set request ID in context for tracing.
    
    This allows correlation of client requests with server logs.
    Client should send trace_id in request metadata.
    """
    request_id_ctx.set(req_id)
    return req_id

def get_request_id() -> str:
    """Get current request ID from context."""
    return request_id_ctx.get()

async def trace_middleware(request, call_next):
    """
    [FIX #7] FastAPI/Starlette middleware to extract trace ID from requests.
    
    Extracts trace_id from JSON-RPC request metadata and sets it in context.
    This enables end-to-end tracing from VS Code to server logs.
    
    Usage in main.py:
        from src.observability import trace_middleware
        app.middleware("http")(trace_middleware)
    """
    trace_id = "unknown"
    
    # Try to extract from JSON body
    try:
        if request.method == "POST":
            body = await request.body()
            import json as json_lib
            data = json_lib.loads(body)
            trace_id = data.get('_meta', {}).get('trace_id', 'unknown')
            
            # Restore body for downstream handlers
            async def receive():
                return {"type": "http.request", "body": body}
            request._receive = receive
    except Exception:
        pass
    
    # Set in context
    token = request_id_ctx.set(trace_id)
    
    try:
        response = await call_next(request)
        return response
    finally:
        request_id_ctx.reset(token)
