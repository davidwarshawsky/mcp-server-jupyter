"""
Tests for ExecutionScheduler Component
========================================

Tests execution queue processing, linearity checking, timeout handling,
and stop_on_error logic.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from src.execution_scheduler import ExecutionScheduler


@pytest.fixture
def scheduler():
    """Create ExecutionScheduler instance for testing."""
    return ExecutionScheduler(default_timeout=10)


@pytest.fixture
def session_data():
    """Create minimal session data structure."""
    return {
        'execution_queue': asyncio.Queue(maxsize=10),
        'queued_executions': {},
        'executions': {},
        'execution_counter': 0,
        'max_executed_index': -1,
        'stop_on_error': False,
        'execution_timeout': 10,
    }


class TestExecutionSchedulerBasics:
    """Test basic scheduler operations."""
    
    def test_initialization(self, scheduler):
        """Test ExecutionScheduler initializes correctly."""
        assert scheduler.default_timeout == 10
    
    async def test_process_queue_shutdown_signal(self, scheduler, session_data):
        """Test that None in queue triggers shutdown."""
        await session_data['execution_queue'].put(None)
        
        execute_callback = AsyncMock()
        
        # Should exit immediately on None
        await scheduler.process_queue(
            nb_path="/test/nb.ipynb",
            session_data=session_data,
            execute_callback=execute_callback
        )
        
        # Callback should not be called
        execute_callback.assert_not_called()


class TestLinearityChecking:
    """Test scientific integrity warnings for non-linear execution."""
    
    def test_linearity_check_first_cell(self, scheduler, session_data):
        """Test no warning for first cell."""
        session_data['max_executed_index'] = -1
        warning = scheduler._check_linearity(session_data, 0)
        assert warning == ""
    
    def test_linearity_check_forward_execution(self, scheduler, session_data):
        """Test no warning for forward (linear) execution."""
        session_data['max_executed_index'] = 2
        warning = scheduler._check_linearity(session_data, 3)
        assert warning == ""
    
    def test_linearity_check_backward_execution(self, scheduler, session_data):
        """Test warning for backward (non-linear) execution."""
        session_data['max_executed_index'] = 5
        warning = scheduler._check_linearity(session_data, 2)
        
        assert "[INTEGRITY WARNING]" in warning
        assert "Cell 3" in warning
        assert "Cell 6" in warning
        assert "hidden state" in warning.lower()


class TestExecutionLifecycle:
    """Test cell execution lifecycle."""
    
    async def test_execute_cell_success(self, scheduler, session_data):
        """Test successful cell execution."""
        # Mock execute callback
        execute_callback = AsyncMock(return_value="msg_123")
        
        # Start execution in background
        exec_task = asyncio.create_task(
            scheduler._execute_cell(
                nb_path="/test/nb.ipynb",
                session_data=session_data,
                cell_index=0,
                code="print('hello')",
                exec_id="exec_001",
                execute_callback=execute_callback
            )
        )
        
        # Wait for execution to register
        await asyncio.sleep(0.1)
        
        # Verify execution was registered
        assert "msg_123" in session_data['executions']
        exec_data = session_data['executions']['msg_123']
        assert exec_data['status'] == 'running'
        assert exec_data['cell_index'] == 0
        assert exec_data['execution_count'] == 1
        
        # Simulate completion
        exec_data['status'] = 'completed'
        
        # Wait for execution to finish
        await exec_task
        
        # Verify finalization event was set
        assert exec_data['finalization_event'].is_set()
    
    async def test_execute_cell_increments_counter(self, scheduler, session_data):
        """Test execution counter increments."""
        execute_callback = AsyncMock(return_value="msg_1")
        
        # Execute first cell
        task1 = asyncio.create_task(
            scheduler._execute_cell(
                nb_path="/test/nb.ipynb",
                session_data=session_data,
                cell_index=0,
                code="x=1",
                exec_id="exec_1",
                execute_callback=execute_callback
            )
        )
        
        await asyncio.sleep(0.1)
        session_data['executions']['msg_1']['status'] = 'completed'
        await task1
        
        assert session_data['execution_counter'] == 1
        
        # Execute second cell
        execute_callback.return_value = "msg_2"
        task2 = asyncio.create_task(
            scheduler._execute_cell(
                nb_path="/test/nb.ipynb",
                session_data=session_data,
                cell_index=1,
                code="y=2",
                exec_id="exec_2",
                execute_callback=execute_callback
            )
        )
        
        await asyncio.sleep(0.1)
        session_data['executions']['msg_2']['status'] = 'completed'
        await task2
        
        assert session_data['execution_counter'] == 2


class TestTimeoutHandling:
    """Test execution timeout behavior."""
    
    async def test_timeout_handling(self, scheduler, session_data):
        """Test execution timeout is detected."""
        # Set very short timeout
        session_data['execution_timeout'] = 1
        
        execute_callback = AsyncMock(return_value="msg_timeout")
        
        # Execute cell (will timeout)
        await scheduler._execute_cell(
            nb_path="/test/nb.ipynb",
            session_data=session_data,
            cell_index=0,
            code="import time; time.sleep(100)",
            exec_id="exec_timeout",
            execute_callback=execute_callback
        )
        
        # Verify timeout status
        exec_data = session_data['executions']['msg_timeout']
        assert exec_data['status'] == 'timeout'
        assert 'exceeded' in exec_data['error'].lower()


class TestStopOnError:
    """Test stop_on_error functionality."""
    
    async def test_stop_on_error_clears_queue(self, scheduler, session_data):
        """Test that stop_on_error=True clears queue on error."""
        session_data['stop_on_error'] = True
        
        # Add items to queue
        await session_data['execution_queue'].put({
            'cell_index': 1,
            'code': 'x=1',
            'exec_id': 'exec_pending1'
        })
        await session_data['execution_queue'].put({
            'cell_index': 2,
            'code': 'y=2',
            'exec_id': 'exec_pending2'
        })
        
        assert session_data['execution_queue'].qsize() == 2
        
        # Trigger clear on error
        await scheduler._clear_queue_on_error(session_data, "test error")
        
        # Queue should be empty
        assert session_data['execution_queue'].qsize() == 0
    
    async def test_stop_on_error_execution_flow(self, scheduler, session_data):
        """Test stop_on_error stops execution flow."""
        session_data['stop_on_error'] = True
        
        execute_callback = AsyncMock(return_value="msg_err")
        
        # Execute cell that will error
        task = asyncio.create_task(
            scheduler._execute_cell(
                nb_path="/test/nb.ipynb",
                session_data=session_data,
                cell_index=0,
                code="raise ValueError('test')",
                exec_id="exec_err",
                execute_callback=execute_callback
            )
        )
        
        # Add pending items to queue
        await session_data['execution_queue'].put({
            'cell_index': 1,
            'code': 'x=1',
            'exec_id': 'exec_pending'
        })
        
        # Simulate error
        await asyncio.sleep(0.1)
        session_data['executions']['msg_err']['status'] = 'error'
        
        await task
        
        # Queue should be cleared due to stop_on_error
        assert session_data['execution_queue'].qsize() == 0
    
    async def test_stop_on_error_disabled_keeps_queue(self, scheduler, session_data):
        """Test that stop_on_error=False keeps queue intact."""
        session_data['stop_on_error'] = False
        
        execute_callback = AsyncMock(return_value="msg_noerr")
        
        # Add pending items to queue
        await session_data['execution_queue'].put({
            'cell_index': 1,
            'code': 'x=1',
            'exec_id': 'exec_pending'
        })
        
        initial_size = session_data['execution_queue'].qsize()
        
        # Execute cell that errors
        task = asyncio.create_task(
            scheduler._execute_cell(
                nb_path="/test/nb.ipynb",
                session_data=session_data,
                cell_index=0,
                code="raise ValueError('test')",
                exec_id="exec_noerr",
                execute_callback=execute_callback
            )
        )
        
        await asyncio.sleep(0.1)
        session_data['executions']['msg_noerr']['status'] = 'error'
        await task
        
        # Queue should remain intact (stop_on_error=False)
        assert session_data['execution_queue'].qsize() == initial_size


class TestQueueProcessing:
    """Test full queue processing workflow."""
    
    async def test_process_queue_basic_flow(self, scheduler, session_data):
        """Test basic queue processing flow."""
        execute_callback = AsyncMock()
        execute_callback.side_effect = ["msg_1", "msg_2"]
        
        # Add two cells to queue
        await session_data['execution_queue'].put({
            'cell_index': 0,
            'code': 'x=1',
            'exec_id': 'exec_1'
        })
        await session_data['execution_queue'].put({
            'cell_index': 1,
            'code': 'y=2',
            'exec_id': 'exec_2'
        })
        await session_data['execution_queue'].put(None)  # Shutdown signal
        
        # Start queue processor
        processor_task = asyncio.create_task(
            scheduler.process_queue(
                nb_path="/test/nb.ipynb",
                session_data=session_data,
                execute_callback=execute_callback
            )
        )
        
        # Let first cell start
        await asyncio.sleep(0.2)
        if 'msg_1' in session_data['executions']:
            session_data['executions']['msg_1']['status'] = 'completed'
        
        # Let second cell start
        await asyncio.sleep(0.2)
        if 'msg_2' in session_data['executions']:
            session_data['executions']['msg_2']['status'] = 'completed'
        
        # Wait for processor to finish
        await processor_task
        
        # Verify both cells were executed
        assert execute_callback.call_count == 2


class TestErrorHandling:
    """Test error handling in execution."""
    
    async def test_exception_in_execute_callback(self, scheduler, session_data):
        """Test that exceptions in execute callback are handled."""
        execute_callback = AsyncMock(side_effect=RuntimeError("Kernel crashed"))
        
        # Execute should handle exception gracefully (no crash)
        await scheduler._execute_cell(
            nb_path="/test/nb.ipynb",
            session_data=session_data,
            cell_index=0,
            code="x=1",
            exec_id="exec_crash",
            execute_callback=execute_callback
        )
        
        # No execution entry should be created since callback failed before kernel.execute()
        # This is correct behavior - if kernel never starts execution, no tracking needed
        assert len(session_data['executions']) == 0


class TestMaxExecutedIndex:
    """Test tracking of max executed index."""
    
    async def test_max_executed_index_updates(self, scheduler, session_data):
        """Test max_executed_index tracks highest cell."""
        execute_callback = AsyncMock()
        execute_callback.side_effect = ["msg_1", "msg_2", "msg_3"]
        
        # Execute cells: 0, 2, 1 (out of order)
        for idx, exec_id in [(0, "e1"), (2, "e2"), (1, "e3")]:
            execute_callback.return_value = f"msg_{exec_id}"
            task = asyncio.create_task(
                scheduler._execute_cell(
                    nb_path="/test/nb.ipynb",
                    session_data=session_data,
                    cell_index=idx,
                    code=f"x={idx}",
                    exec_id=exec_id,
                    execute_callback=execute_callback
                )
            )
            
            await asyncio.sleep(0.1)
            msg_id = f"msg_{exec_id}"
            if msg_id in session_data['executions']:
                session_data['executions'][msg_id]['status'] = 'completed'
            await task
        
        # Max should be 2 (highest index executed)
        assert session_data['max_executed_index'] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
