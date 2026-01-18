"""
Tests for Phase 5.1: Structured Audit Log

Tests the audit logging functionality including:
- Structured log format
- trace_id propagation
- Duration tracking
- Volume limits
- Decorator usage
"""

import pytest
import asyncio
import json
import time
from unittest.mock import patch, MagicMock

from src.audit_log import (
    AuditLogger,
    audit_tool,
    set_trace_id,
    get_trace_id,
    generate_trace_id,
    audit_logger
)


class TestAuditLogger:
    """Test AuditLogger class."""
    
    def test_initialization(self):
        """Test logger initialization."""
        logger = AuditLogger(log_volume_limit_mb=2.0)
        
        assert logger.log_volume_limit_mb == 2.0
        assert logger.bytes_logged == 0
        assert logger.hour_start > 0
    
    @patch('src.audit_log.logger')
    def test_log_tool_execution_success(self, mock_logger):
        """Test logging successful tool execution."""
        logger = AuditLogger()
        
        logger.log_tool_execution(
            tool="run_cell",
            status="success",
            duration_ms=123.45,
            trace_id="abc123",
            metadata={"kernel_id": "kernel-1"}
        )
        
        # Verify info level used for success
        assert mock_logger.info.called
        
        # Parse logged JSON
        log_call = mock_logger.info.call_args[0][0]
        assert "AUDIT:" in log_call
        
        # Extract JSON part
        json_part = log_call.split("AUDIT: ")[1]
        event = json.loads(json_part)
        
        assert event["event"] == "tool_execution"
        assert event["tool"] == "run_cell"
        assert event["status"] == "success"
        assert event["duration_ms"] == 123.45
        assert event["trace_id"] == "abc123"
        assert event["metadata"]["kernel_id"] == "kernel-1"
    
    @patch('src.audit_log.logger')
    def test_log_tool_execution_error(self, mock_logger):
        """Test logging failed tool execution."""
        logger = AuditLogger()
        
        logger.log_tool_execution(
            tool="run_cell",
            status="error",
            duration_ms=50.0,
            trace_id="xyz789",
            metadata={"error": "Division by zero"}
        )
        
        # Verify error level used
        assert mock_logger.error.called
    
    @patch('src.audit_log.logger')
    def test_log_kernel_event(self, mock_logger):
        """Test logging kernel lifecycle events."""
        logger = AuditLogger()
        
        logger.log_kernel_event(
            event_type="start",
            kernel_id="kernel-123",
            status="success",
            trace_id="trace-1"
        )
        
        assert mock_logger.info.called
        
        log_call = mock_logger.info.call_args[0][0]
        json_part = log_call.split("AUDIT: ")[1]
        event = json.loads(json_part)
        
        assert event["event"] == "kernel_lifecycle"
        assert event["event_type"] == "start"
        assert event["kernel_id"] == "kernel-123"
        assert event["status"] == "success"
    
    @patch('src.audit_log.logger')
    def test_volume_limit_warning(self, mock_logger):
        """Test that exceeding volume limit triggers warning."""
        # Small limit for testing
        logger = AuditLogger(log_volume_limit_mb=0.001)  # 1KB
        
        # Log many events to exceed limit
        for i in range(100):
            logger.log_tool_execution(
                tool="test_tool",
                status="success",
                duration_ms=1.0,
                metadata={"data": "x" * 100}  # Add bulk
            )
        
        # Should have warning about volume
        warning_calls = [c for c in mock_logger.warning.call_args_list 
                        if "Log volume exceeded" in str(c)]
        assert len(warning_calls) > 0
    
    def test_volume_counter_resets_hourly(self):
        """Test that volume counter resets after an hour."""
        logger = AuditLogger()
        
        # Log some data
        logger.bytes_logged = 500000  # 500KB
        logger.hour_start = time.time() - 3700  # Over an hour ago
        
        # Log new event (should trigger reset)
        with patch('src.audit_log.logger'):
            logger.log_tool_execution(
                tool="test",
                status="success",
                duration_ms=1.0
            )
        
        # Counter should be reset
        assert logger.bytes_logged < 500000


class TestTraceIdPropagation:
    """Test trace_id context propagation."""
    
    def test_set_and_get_trace_id(self):
        """Test setting and getting trace_id."""
        trace_id = "test-trace-123"
        set_trace_id(trace_id)
        
        assert get_trace_id() == trace_id
    
    def test_generate_trace_id_format(self):
        """Test that generated trace_id has correct format."""
        trace_id = generate_trace_id()
        
        assert isinstance(trace_id, str)
        assert len(trace_id) == 8  # Truncated UUID
        assert all(c in '0123456789abcdef-' for c in trace_id.lower())
    
    def test_generate_trace_id_unique(self):
        """Test that generated trace_ids are unique."""
        ids = [generate_trace_id() for _ in range(100)]
        
        assert len(set(ids)) == 100  # All unique


class TestAuditToolDecorator:
    """Test @audit_tool decorator."""
    
    @pytest.mark.asyncio
    async def test_async_function_success(self):
        """Test decorator on successful async function."""
        @audit_tool
        async def test_async_func(value: int):
            await asyncio.sleep(0.01)
            return value * 2
        
        with patch.object(audit_logger, 'log_tool_execution') as mock_log:
            result = await test_async_func(5)
            
            assert result == 10
            assert mock_log.called
            
            # Verify logged data
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs['tool'] == 'test_async_func'
            assert call_kwargs['status'] == 'success'
            assert call_kwargs['duration_ms'] > 0
            assert call_kwargs['trace_id'] is not None
    
    @pytest.mark.asyncio
    async def test_async_function_error(self):
        """Test decorator on failing async function."""
        @audit_tool
        async def test_async_func_error():
            await asyncio.sleep(0.01)
            raise ValueError("Test error")
        
        with patch.object(audit_logger, 'log_tool_execution') as mock_log:
            with pytest.raises(ValueError, match="Test error"):
                await test_async_func_error()
            
            # Should still log the error
            assert mock_log.called
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs['status'] == 'error'
            assert 'error_type' in call_kwargs['metadata']
            assert call_kwargs['metadata']['error_type'] == 'ValueError'
    
    def test_sync_function_success(self):
        """Test decorator on successful sync function."""
        @audit_tool
        def test_sync_func(a: int, b: int):
            return a + b
        
        with patch.object(audit_logger, 'log_tool_execution') as mock_log:
            result = test_sync_func(3, 4)
            
            assert result == 7
            assert mock_log.called
            
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs['tool'] == 'test_sync_func'
            assert call_kwargs['status'] == 'success'
    
    def test_sync_function_error(self):
        """Test decorator on failing sync function."""
        @audit_tool
        def test_sync_func_error():
            raise RuntimeError("Sync error")
        
        with patch.object(audit_logger, 'log_tool_execution') as mock_log:
            with pytest.raises(RuntimeError, match="Sync error"):
                test_sync_func_error()
            
            assert mock_log.called
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs['status'] == 'error'
    
    @pytest.mark.asyncio
    async def test_metadata_extraction(self):
        """Test that decorator extracts metadata from kwargs."""
        @audit_tool
        async def test_func(kernel_id: str, cell_index: int, other: str):
            return "result"
        
        with patch.object(audit_logger, 'log_tool_execution') as mock_log:
            await test_func(
                kernel_id="kernel-123",
                cell_index=5,
                other="ignored"
            )
            
            call_kwargs = mock_log.call_args[1]
            metadata = call_kwargs['metadata']
            
            assert metadata['kernel_id'] == "kernel-123"
            assert metadata['cell_index'] == 5
            assert 'other' not in metadata  # Not tracked


class TestLogFormat:
    """Test structured log format compliance."""
    
    @patch('src.audit_log.logger')
    def test_json_format(self, mock_logger):
        """Test that logs are valid JSON."""
        logger = AuditLogger()
        
        logger.log_tool_execution(
            tool="test",
            status="success",
            duration_ms=100.0,
            trace_id="abc"
        )
        
        log_call = mock_logger.info.call_args[0][0]
        json_part = log_call.split("AUDIT: ")[1]
        
        # Should parse without error
        event = json.loads(json_part)
        assert isinstance(event, dict)
    
    @patch('src.audit_log.logger')
    def test_required_fields(self, mock_logger):
        """Test that all required fields are present."""
        logger = AuditLogger()
        
        logger.log_tool_execution(
            tool="test",
            status="success",
            duration_ms=50.0
        )
        
        log_call = mock_logger.info.call_args[0][0]
        json_part = log_call.split("AUDIT: ")[1]
        event = json.loads(json_part)
        
        # Required fields
        required = ["event", "tool", "trace_id", "duration_ms", "status", "timestamp"]
        for field in required:
            assert field in event
    
    @patch('src.audit_log.logger')
    def test_duration_precision(self, mock_logger):
        """Test that duration is rounded to 2 decimal places."""
        logger = AuditLogger()
        
        logger.log_tool_execution(
            tool="test",
            status="success",
            duration_ms=123.456789
        )
        
        log_call = mock_logger.info.call_args[0][0]
        json_part = log_call.split("AUDIT: ")[1]
        event = json.loads(json_part)
        
        # Should be rounded to 2 decimals
        assert event["duration_ms"] == 123.46


class TestPerformance:
    """Test audit logger performance."""
    
    def test_logging_overhead_minimal(self):
        """Test that logging doesn't add significant overhead."""
        logger = AuditLogger()
        
        start = time.time()
        
        with patch('src.audit_log.logger'):
            for _ in range(1000):
                logger.log_tool_execution(
                    tool="test",
                    status="success",
                    duration_ms=1.0
                )
        
        elapsed = time.time() - start
        
        # Should complete 1000 logs in under 1 second
        assert elapsed < 1.0
