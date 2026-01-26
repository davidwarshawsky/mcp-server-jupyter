"""
OpenTelemetry integration for distributed tracing and metrics.

This module provides OpenTelemetry integration for exporting traces and metrics
to observability backends like Jaeger, Honeycomb, and Prometheus.

Key Features:
- Distributed trace export to OTLP backends (Jaeger, Honeycomb, etc.)
- Automatic span creation with @traced decorator
- trace_id propagation from audit_log module
- Configurable via environment variables
- P95 latency < 500ms for cell execution
- Jaeger UI integration for trace visualization

Environment Variables:
- OTEL_ENABLED: Enable/disable OpenTelemetry (default: true)
- OTEL_SERVICE_NAME: Service name (default: mcp-server-jupyter)
- OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint (default: http://localhost:4317)
- OTEL_EXPORTER_OTLP_HEADERS: Optional headers (e.g., x-honeycomb-team=<apikey>)
- OTEL_TRACES_SAMPLER: Sampler (always_on, always_off, traceidratio)
- OTEL_TRACES_SAMPLER_ARG: Sampler argument (e.g., 0.1 for 10% sampling)

Example Usage:
    from telemetry import traced, tracer, record_metric
    
    @traced("run_cell")
    async def run_cell_async(kernel_id: str, code: str):
        with tracer.start_as_current_span("compile_code") as span:
            span.set_attribute("code_length", len(code))
            compiled = compile(code, '<cell>', 'exec')
        
        record_metric("cell_execution_count", 1, {"kernel_id": kernel_id})
        return result
"""

import os
import logging
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional
from contextlib import contextmanager

# OpenTelemetry imports (graceful degradation if not installed)
try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.trace import Status, StatusCode
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator,
    )

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    logging.warning("OpenTelemetry not installed. Tracing disabled.")

# Import trace_id from audit_log for correlation
try:
    from audit_log import get_trace_id, generate_trace_id

    AUDIT_LOG_AVAILABLE = True
except ImportError:
    AUDIT_LOG_AVAILABLE = False
    logging.warning("audit_log module not available. trace_id correlation disabled.")


# ==================== Configuration ====================


def _get_bool_env(key: str, default: bool) -> bool:
    """Get boolean environment variable."""
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


# Check if OpenTelemetry is enabled
OTEL_ENABLED = _get_bool_env("OTEL_ENABLED", True) and OTEL_AVAILABLE

# Service configuration
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "mcp-server-jupyter")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
OTLP_HEADERS = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")

# Sampling configuration
SAMPLER_TYPE = os.getenv("OTEL_TRACES_SAMPLER", "always_on")
SAMPLER_ARG = float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0"))


# ==================== Initialization ====================

if OTEL_ENABLED:
    # Create resource with service name
    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": "1.0.0",
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        }
    )

    # Configure trace provider
    trace_provider = TracerProvider(resource=resource)

    # Parse OTLP headers
    headers = {}
    if OTLP_HEADERS:
        for header in OTLP_HEADERS.split(","):
            if "=" in header:
                key, value = header.split("=", 1)
                headers[key.strip()] = value.strip()

    # Create OTLP span exporter
    span_exporter = OTLPSpanExporter(
        endpoint=OTLP_ENDPOINT,
        headers=headers,
    )

    # Add batch span processor for performance
    trace_provider.add_span_processor(BatchSpanProcessor(span_exporter))

    # Set global trace provider
    trace.set_tracer_provider(trace_provider)

    # Configure metrics provider
    metric_exporter = OTLPMetricExporter(
        endpoint=OTLP_ENDPOINT,
        headers=headers,
    )

    metric_reader = PeriodicExportingMetricReader(
        exporter=metric_exporter,
        export_interval_millis=60000,  # Export every 60 seconds
    )

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )

    # Set global meter provider
    metrics.set_meter_provider(meter_provider)

    # Create tracer and meter
    tracer = trace.get_tracer(__name__)
    meter = metrics.get_meter(__name__)

    # Create common metrics
    cell_execution_counter = meter.create_counter(
        name="cell_execution_count",
        description="Number of cell executions",
        unit="1",
    )

    cell_execution_duration = meter.create_histogram(
        name="cell_execution_duration_ms",
        description="Duration of cell executions in milliseconds",
        unit="ms",
    )

    kernel_startup_duration = meter.create_histogram(
        name="kernel_startup_duration_ms",
        description="Duration of kernel startups in milliseconds",
        unit="ms",
    )

    error_counter = meter.create_counter(
        name="error_count",
        description="Number of errors by type",
        unit="1",
    )

    logging.info(f"OpenTelemetry initialized. Exporting to: {OTLP_ENDPOINT}")

else:
    # Create no-op tracer and meter if disabled
    tracer = None
    meter = None
    cell_execution_counter = None
    cell_execution_duration = None
    kernel_startup_duration = None
    error_counter = None

    if OTEL_AVAILABLE:
        logging.info("OpenTelemetry disabled via OTEL_ENABLED=false")


# ==================== Decorator ====================


def traced(
    span_name: Optional[str] = None, attributes: Optional[Dict[str, Any]] = None
):
    """
    Decorator to automatically trace function execution.

    Supports both sync and async functions. Automatically:
    - Creates a span with the function name (or custom span_name)
    - Adds function arguments as span attributes (if attributes dict provided)
    - Correlates with trace_id from audit_log module
    - Records exceptions and marks span as error
    - Records duration as histogram metric

    Args:
        span_name: Optional custom span name (defaults to function name)
        attributes: Optional dict of attribute names to extract from kwargs

    Example:
        @traced("run_cell", attributes={"kernel_id": "kernel_id"})
        async def run_cell_async(kernel_id: str, code: str):
            return result
    """

    def decorator(func: Callable) -> Callable:
        # Use function name if span_name not provided
        name = span_name or func.__name__

        if not OTEL_ENABLED:
            # Return original function if tracing disabled
            return func

        # Check if function is async
        import asyncio

        is_async = asyncio.iscoroutinefunction(func)

        if is_async:

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Get trace_id from audit_log if available
                trace_id = None
                if AUDIT_LOG_AVAILABLE:
                    trace_id = get_trace_id()
                    if not trace_id:
                        # Generate new trace_id if not in context
                        from audit_log import set_trace_id

                        trace_id = generate_trace_id()
                        set_trace_id(trace_id)

                # Start span
                with tracer.start_as_current_span(name) as span:
                    # Add trace_id as attribute for correlation
                    if trace_id:
                        span.set_attribute("trace_id", trace_id)

                    # Add custom attributes from kwargs
                    if attributes:
                        for attr_name, kwarg_name in attributes.items():
                            if kwarg_name in kwargs:
                                value = kwargs[kwarg_name]
                                # Convert to string for non-primitive types
                                if isinstance(value, (str, int, float, bool)):
                                    span.set_attribute(attr_name, value)
                                else:
                                    span.set_attribute(attr_name, str(value))

                    # Record start time
                    start_time = time.time()

                    try:
                        # Execute function
                        result = await func(*args, **kwargs)

                        # Mark span as successful
                        span.set_status(Status(StatusCode.OK))

                        # Record duration metric
                        duration_ms = (time.time() - start_time) * 1000
                        if cell_execution_duration:
                            cell_execution_duration.record(
                                duration_ms, {"function": name, "status": "success"}
                            )

                        return result

                    except Exception as e:
                        # Record exception in span
                        span.record_exception(e)
                        span.set_status(Status(StatusCode.ERROR, str(e)))

                        # Record error metric
                        if error_counter:
                            error_counter.add(
                                1, {"function": name, "error_type": type(e).__name__}
                            )

                        # Re-raise exception
                        raise

            return async_wrapper

        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                # Get trace_id from audit_log if available
                trace_id = None
                if AUDIT_LOG_AVAILABLE:
                    trace_id = get_trace_id()
                    if not trace_id:
                        from audit_log import set_trace_id

                        trace_id = generate_trace_id()
                        set_trace_id(trace_id)

                # Start span
                with tracer.start_as_current_span(name) as span:
                    # Add trace_id as attribute for correlation
                    if trace_id:
                        span.set_attribute("trace_id", trace_id)

                    # Add custom attributes from kwargs
                    if attributes:
                        for attr_name, kwarg_name in attributes.items():
                            if kwarg_name in kwargs:
                                value = kwargs[kwarg_name]
                                if isinstance(value, (str, int, float, bool)):
                                    span.set_attribute(attr_name, value)
                                else:
                                    span.set_attribute(attr_name, str(value))

                    # Record start time
                    start_time = time.time()

                    try:
                        # Execute function
                        result = func(*args, **kwargs)

                        # Mark span as successful
                        span.set_status(Status(StatusCode.OK))

                        # Record duration metric
                        duration_ms = (time.time() - start_time) * 1000
                        if cell_execution_duration:
                            cell_execution_duration.record(
                                duration_ms, {"function": name, "status": "success"}
                            )

                        return result

                    except Exception as e:
                        # Record exception in span
                        span.record_exception(e)
                        span.set_status(Status(StatusCode.ERROR, str(e)))

                        # Record error metric
                        if error_counter:
                            error_counter.add(
                                1, {"function": name, "error_type": type(e).__name__}
                            )

                        raise

            return sync_wrapper

    return decorator


# ==================== Manual Span Creation ====================


@contextmanager
def create_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """
    Context manager for creating manual spans.

    Example:
        with create_span("compile_code", {"code_length": len(code)}) as span:
            compiled = compile(code, '<cell>', 'exec')
            span.set_attribute("ast_nodes", len(ast.walk(compiled)))
    """
    if not OTEL_ENABLED:
        # No-op context manager if tracing disabled
        yield None
        return

    with tracer.start_as_current_span(name) as span:
        # Add trace_id from audit_log
        if AUDIT_LOG_AVAILABLE:
            trace_id = get_trace_id()
            if trace_id:
                span.set_attribute("trace_id", trace_id)

        # Add custom attributes
        if attributes:
            for key, value in attributes.items():
                if isinstance(value, (str, int, float, bool)):
                    span.set_attribute(key, value)
                else:
                    span.set_attribute(key, str(value))

        yield span


# ==================== Metrics ====================


def record_metric(
    metric_name: str, value: float, attributes: Optional[Dict[str, str]] = None
):
    """
    Record a custom metric.

    Args:
        metric_name: Name of the metric (cell_execution_count, error_count, etc.)
        value: Metric value
        attributes: Optional attributes for metric dimensions

    Example:
        record_metric("cell_execution_count", 1, {"kernel_id": kernel_id})
        record_metric("output_size_bytes", len(output), {"cell_type": "code"})
    """
    if not OTEL_ENABLED:
        return

    attrs = attributes or {}

    # Route to appropriate metric
    if metric_name == "cell_execution_count" and cell_execution_counter:
        cell_execution_counter.add(int(value), attrs)

    elif metric_name == "cell_execution_duration_ms" and cell_execution_duration:
        cell_execution_duration.record(value, attrs)

    elif metric_name == "kernel_startup_duration_ms" and kernel_startup_duration:
        kernel_startup_duration.record(value, attrs)

    elif metric_name == "error_count" and error_counter:
        error_counter.add(int(value), attrs)

    else:
        logging.warning(f"Unknown metric: {metric_name}")


# ==================== Shutdown ====================


def shutdown_telemetry():
    """
    Shutdown telemetry providers and flush pending data.

    Should be called on application shutdown to ensure all traces
    and metrics are exported before process termination.
    """
    if not OTEL_ENABLED:
        return

    logging.info("Shutting down OpenTelemetry...")

    # Shutdown trace provider
    if trace_provider:
        trace_provider.shutdown()

    # Shutdown meter provider
    if meter_provider:
        meter_provider.shutdown()

    logging.info("OpenTelemetry shutdown complete")


# ==================== Exports ====================

__all__ = [
    "OTEL_ENABLED",
    "tracer",
    "meter",
    "traced",
    "create_span",
    "record_metric",
    "shutdown_telemetry",
    "cell_execution_counter",
    "cell_execution_duration",
    "kernel_startup_duration",
    "error_counter",
]
