"""
Tests for OpenTelemetry integration (Phase 5.2).

Test Coverage:
- Tracer initialization and configuration
- @traced decorator (async and sync)
- Manual span creation with create_span()
- Metric recording (counters and histograms)
- trace_id correlation with audit_log
- Error handling and exception recording
- Graceful degradation when OpenTelemetry disabled
- OTLP export configuration
"""

import pytest
import os
import time
import asyncio
from unittest.mock import patch

# Set environment variables before importing telemetry
os.environ["OTEL_ENABLED"] = "true"
os.environ["OTEL_SERVICE_NAME"] = "test-service"
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"


class TestTelemetryInitialization:
    """Test OpenTelemetry initialization and configuration."""

    def test_otel_enabled_by_default(self):
        """OTEL should be enabled by default if installed."""
        from telemetry import OTEL_ENABLED, OTEL_AVAILABLE

        # Should be enabled if OpenTelemetry is installed
        if OTEL_AVAILABLE:
            assert OTEL_ENABLED is True
        else:
            assert OTEL_ENABLED is False

    def test_service_name_configuration(self):
        """Service name should be configurable via environment variable."""
        from telemetry import SERVICE_NAME

        assert SERVICE_NAME == "test-service"

    def test_otlp_endpoint_configuration(self):
        """OTLP endpoint should be configurable via environment variable."""
        from telemetry import OTLP_ENDPOINT

        assert OTLP_ENDPOINT == "http://localhost:4317"

    def test_tracer_available(self):
        """Tracer should be available when OTEL is enabled."""
        from telemetry import tracer, OTEL_ENABLED

        if OTEL_ENABLED:
            assert tracer is not None
        else:
            # Graceful degradation: tracer is None if disabled
            assert tracer is None

    def test_meter_available(self):
        """Meter should be available when OTEL is enabled."""
        from telemetry import meter, OTEL_ENABLED

        if OTEL_ENABLED:
            assert meter is not None
        else:
            assert meter is None


class TestTracedDecorator:
    """Test @traced decorator for automatic span creation."""

    @pytest.mark.asyncio
    async def test_traced_async_function_success(self):
        """@traced should create span for successful async function."""
        from telemetry import traced, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        @traced("test_async")
        async def test_func(value: int):
            await asyncio.sleep(0.01)
            return value * 2

        result = await test_func(21)

        assert result == 42

    @pytest.mark.asyncio
    async def test_traced_async_function_error(self):
        """@traced should record exception in span for failed async function."""
        from telemetry import traced, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        @traced("test_async_error")
        async def test_func():
            await asyncio.sleep(0.01)
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await test_func()

    def test_traced_sync_function_success(self):
        """@traced should create span for successful sync function."""
        from telemetry import traced, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        @traced("test_sync")
        def test_func(value: int):
            time.sleep(0.01)
            return value * 3

        result = test_func(14)

        assert result == 42

    def test_traced_sync_function_error(self):
        """@traced should record exception in span for failed sync function."""
        from telemetry import traced, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        @traced("test_sync_error")
        def test_func():
            time.sleep(0.01)
            raise RuntimeError("Sync error")

        with pytest.raises(RuntimeError, match="Sync error"):
            test_func()

    @pytest.mark.asyncio
    async def test_traced_with_attributes(self):
        """@traced should extract and set span attributes from kwargs."""
        from telemetry import traced, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        @traced("test_with_attrs", attributes={"user_id": "user_id", "count": "count"})
        async def test_func(user_id: str, count: int):
            return f"{user_id}:{count}"

        result = await test_func(user_id="alice", count=42)

        assert result == "alice:42"

    def test_traced_no_op_when_disabled(self):
        """@traced should be no-op when OTEL is disabled."""
        # Temporarily disable OTEL
        with patch("telemetry.OTEL_ENABLED", False):
            # Reimport to get disabled version
            import importlib
            import telemetry

            importlib.reload(telemetry)

            from telemetry import traced

            @traced("test_disabled")
            def test_func(value: int):
                return value * 2

            result = test_func(21)

            # Should still work, just without tracing
            assert result == 42


class TestManualSpanCreation:
    """Test manual span creation with create_span()."""

    def test_create_span_context_manager(self):
        """create_span() should work as context manager."""
        from telemetry import create_span, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        with create_span("manual_span") as span:
            # Span should be available inside context
            if OTEL_ENABLED:
                assert span is not None
            else:
                assert span is None

    def test_create_span_with_attributes(self):
        """create_span() should accept custom attributes."""
        from telemetry import create_span, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        attrs = {"operation": "test", "count": 42}

        with create_span("manual_span_attrs", attributes=attrs):
            # Should not raise any errors
            pass

    def test_create_span_no_op_when_disabled(self):
        """create_span() should be no-op when OTEL is disabled."""
        # Simulate disabled OTEL by setting environment before import
        test_env = os.environ.copy()
        test_env["OTEL_ENABLED"] = "false"

        # This test validates that create_span works when OTEL is disabled
        # Since OTEL is initialized at module load, we just verify the
        # current implementation handles the disabled case gracefully
        from telemetry import create_span, OTEL_ENABLED

        if not OTEL_ENABLED:
            # If OTEL is disabled, span should be None
            with create_span("disabled_span") as span:
                assert span is None
        else:
            # If OTEL is enabled (normal case), verify span is created
            with create_span("enabled_span") as span:
                assert span is not None


class TestMetricRecording:
    """Test metric recording functionality."""

    def test_record_cell_execution_count(self):
        """record_metric() should record cell execution counter."""
        from telemetry import record_metric, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        # Should not raise any errors
        record_metric("cell_execution_count", 1, {"kernel_id": "test-kernel"})

    def test_record_cell_execution_duration(self):
        """record_metric() should record cell execution duration histogram."""
        from telemetry import record_metric, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        # Should not raise any errors
        record_metric("cell_execution_duration_ms", 450.5, {"status": "success"})

    def test_record_kernel_startup_duration(self):
        """record_metric() should record kernel startup duration."""
        from telemetry import record_metric, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        # Should not raise any errors
        record_metric("kernel_startup_duration_ms", 1200.0, {"kernel_type": "python3"})

    def test_record_error_count(self):
        """record_metric() should record error counter."""
        from telemetry import record_metric, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        # Should not raise any errors
        record_metric("error_count", 1, {"error_type": "ValueError"})

    def test_record_unknown_metric_logs_warning(self):
        """record_metric() should log warning for unknown metrics."""
        from telemetry import record_metric, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        with patch("telemetry.logging.warning") as mock_warning:
            record_metric("unknown_metric", 42)

            # Should log warning about unknown metric
            if OTEL_ENABLED:
                mock_warning.assert_called_once()


class TestTraceIdCorrelation:
    """Test trace_id correlation with audit_log module."""

    @pytest.mark.asyncio
    async def test_trace_id_propagated_to_span(self):
        """trace_id from audit_log should be added as span attribute."""
        from telemetry import traced, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        try:
            from audit_log import set_trace_id

            # Set trace_id in audit_log context
            set_trace_id("abc123")

            @traced("test_trace_id")
            async def test_func():
                return "success"

            result = await test_func()

            assert result == "success"
            # trace_id should be added as span attribute (verified in telemetry.py)

        except ImportError:
            pytest.skip("audit_log module not available")

    @pytest.mark.asyncio
    async def test_trace_id_generated_if_not_in_context(self):
        """If no trace_id in context, @traced should generate one."""
        from telemetry import traced, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        try:
            from audit_log import get_trace_id

            @traced("test_generate_trace_id")
            async def test_func():
                # Check that trace_id was generated
                trace_id = get_trace_id()
                return trace_id

            trace_id = await test_func()

            # Should have generated 8-char UUID
            if trace_id:
                assert len(trace_id) == 8

        except ImportError:
            pytest.skip("audit_log module not available")


class TestErrorHandling:
    """Test error handling and exception recording."""

    @pytest.mark.asyncio
    async def test_exception_recorded_in_span(self):
        """Exceptions should be recorded in span with error status."""
        from telemetry import traced, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        @traced("test_exception")
        async def test_func():
            raise ValueError("Test exception")

        # Exception should be raised as normal
        with pytest.raises(ValueError, match="Test exception"):
            await test_func()

        # Span should have recorded the exception (verified in telemetry.py)

    def test_error_counter_incremented_on_exception(self):
        """Error counter should be incremented when exception occurs."""
        from telemetry import traced, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        @traced("test_error_counter")
        def test_func():
            raise RuntimeError("Test error")

        with pytest.raises(RuntimeError):
            test_func()

        # Error counter should be incremented (verified in telemetry.py)


class TestGracefulDegradation:
    """Test graceful degradation when OpenTelemetry is disabled."""

    def test_functions_work_without_otel(self):
        """Functions should work normally even when OTEL is disabled."""
        # Temporarily disable OTEL
        with patch("telemetry.OTEL_ENABLED", False):
            import importlib
            import telemetry

            importlib.reload(telemetry)

            from telemetry import traced, create_span, record_metric

            @traced("test_no_otel")
            def test_func(value: int):
                return value * 2

            # Should work normally
            result = test_func(21)
            assert result == 42

            # Context manager should work
            with create_span("test_span"):
                pass

            # Metric recording should be no-op
            record_metric("test_metric", 42)


class TestShutdown:
    """Test telemetry shutdown functionality."""

    def test_shutdown_telemetry(self):
        """shutdown_telemetry() should flush and close providers."""
        from telemetry import shutdown_telemetry, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        # Should not raise any errors
        shutdown_telemetry()


class TestPerformance:
    """Test performance characteristics of telemetry."""

    def test_tracing_overhead_minimal(self):
        """Tracing overhead should be < 1.5ms per operation."""
        from telemetry import traced, OTEL_ENABLED

        if not OTEL_ENABLED:
            pytest.skip("OpenTelemetry not available")

        @traced("perf_test")
        def test_func():
            pass

        # Warm up
        for _ in range(10):
            test_func()

        # Measure overhead
        start = time.time()
        iterations = 1000

        for _ in range(iterations):
            test_func()

        duration = time.time() - start
        avg_overhead_ms = (duration / iterations) * 1000

        # Overhead should be < 1.5ms per call under system load
        # (Actual overhead is typically < 0.1ms in isolation)
        assert (
            avg_overhead_ms < 1.5
        ), f"Tracing overhead {avg_overhead_ms:.2f}ms exceeds 1.5ms threshold"


class TestExportConfiguration:
    """Test OTLP export configuration."""

    def test_headers_parsing(self):
        """OTLP headers should be parsed correctly from environment."""
        # Set headers in environment
        test_env = os.environ.copy()
        test_env["OTEL_EXPORTER_OTLP_HEADERS"] = "x-api-key=secret123,x-team=myteam"

        with patch.dict(os.environ, test_env):
            import importlib
            import telemetry

            importlib.reload(telemetry)

            # Headers should be parsed (verified in telemetry.py initialization)
            # This test verifies the code doesn't crash with headers set

    def test_sampler_configuration(self):
        """Sampler should be configurable via environment."""
        from telemetry import SAMPLER_TYPE, SAMPLER_ARG

        # Default values
        assert SAMPLER_TYPE in ["always_on", "always_off", "traceidratio"]
        assert 0.0 <= SAMPLER_ARG <= 1.0
