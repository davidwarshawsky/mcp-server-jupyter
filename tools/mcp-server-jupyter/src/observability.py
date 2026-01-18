import sys
import logging
import structlog
import uuid
import contextvars
from typing import Any, Dict
import os

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

    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
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
