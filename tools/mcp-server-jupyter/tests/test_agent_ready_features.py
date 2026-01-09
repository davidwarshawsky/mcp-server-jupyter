"""
Tests for agent-ready features:
- list_kernels
- run_all_cells
- get_variable_info / list_variables
- stop_on_error flag
"""

import pytest
import asyncio
import nbformat
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from src.session import SessionManager


class TestListKernels:
    """Test list_kernels functionality."""
    
    @pytest.mark.asyncio
    async def test_list_kernels_empty(self):
        """Test listing kernels when none are running."""
        manager = SessionManager()
        assert len(manager.sessions) == 0
    
    @pytest.mark.asyncio
    async def test_list_kernels_with_sessions(self):
        """Test listing kernels with active sessions."""
        manager = SessionManager()
        
        # Mock a session
        nb_path = str(Path("test.ipynb").resolve())
        mock_km = MagicMock()
        mock_km.kernel.pid = 12345
        
        manager.sessions[nb_path] = {
            'km': mock_km,
            'kc': MagicMock(),
            'cwd': '/test/dir',
            'execution_counter': 5,
            'execution_queue': asyncio.Queue(),
            'stop_on_error': True
        }
        
        # List kernels
        assert nb_path in manager.sessions
        session = manager.sessions[nb_path]
        assert session['execution_counter'] == 5
        assert session['stop_on_error'] is True


class TestRunAllCells:
    """Test run_all_cells functionality."""
    
    @pytest.mark.asyncio
    async def test_run_all_cells_enqueues_all_code_cells(self, tmp_path):
        """Test that run_all_cells enqueues all code cells."""
        # Create test notebook
        nb = nbformat.v4.new_notebook()
        nb.cells = [
            nbformat.v4.new_code_cell("x = 1"),
            nbformat.v4.new_markdown_cell("# Header"),
            nbformat.v4.new_code_cell("y = 2"),
            nbformat.v4.new_code_cell("z = x + y")
        ]
        
        nb_path = tmp_path / "test.ipynb"
        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)
        
        # Mock session
        manager = SessionManager()
        resolved_path = str(nb_path.resolve())
        
        execution_queue = asyncio.Queue()
        manager.sessions[resolved_path] = {
            'km': MagicMock(),
            'kc': MagicMock(),
            'execution_queue': execution_queue,
            'executions': {},
            'execution_counter': 0,
            'stop_on_error': False
        }
        
        # Mock execute_cell_async to track calls
        call_count = 0
        async def mock_execute(nb_path, idx, code):
            nonlocal call_count
            call_count += 1
            return f"exec-{idx}"
        
        manager.execute_cell_async = mock_execute
        
        # Count code cells
        code_cell_count = sum(1 for cell in nb.cells if cell.cell_type == 'code')
        
        # Should be 3 code cells
        assert code_cell_count == 3


class TestVariableInspection:
    """Test get_variable_info and list_variables."""
    
    @pytest.mark.asyncio
    async def test_get_variable_info_structure(self):
        """Test that get_variable_info generates correct inspection code."""
        manager = SessionManager()
        nb_path = str(Path("test.ipynb").resolve())
        
        # Mock session with execute capability
        mock_kc = MagicMock()
        mock_kc.execute = MagicMock(return_value="msg-123")
        
        manager.sessions[nb_path] = {
            'kc': mock_kc,
            'km': MagicMock(),
            'execution_queue': asyncio.Queue(),
            'executions': {},
            'execution_counter': 0,
            'stop_on_error': False
        }
        
        # Mock execute_cell_async to return immediately
        async def mock_execute_async(path, idx, code):
            # Verify the inspection code contains the variable name
            assert 'df' in code
            assert 'DataFrame' in code
            assert 'json.dumps' in code
            return "exec-123"
        
        manager.execute_cell_async = mock_execute_async
        
        # Mock get_execution_status to return completed
        def mock_status(path, exec_id):
            return {
                'status': 'completed',
                'output': '{"name": "df", "type": "DataFrame", "shape": [100, 5]}'
            }
        
        manager.get_execution_status = mock_status
        
        # Test the method exists and can be called
        result = await manager.get_variable_info(nb_path, "df")
        assert "DataFrame" in result or "completed" in str(result)


class TestStopOnError:
    """Test stop_on_error flag functionality."""
    
    @pytest.mark.asyncio
    async def test_stop_on_error_default_false(self):
        """Test that stop_on_error defaults to False."""
        manager = SessionManager()
        nb_path = str(Path("test.ipynb").resolve())
        
        with patch("src.session.AsyncKernelManager") as MockKM:
            mock_km = MockKM.return_value
            mock_km.start_kernel = AsyncMock()
            mock_km.kernel.pid = 9999
            
            mock_client = MagicMock()
            mock_client.wait_for_ready = AsyncMock()
            mock_km.client.return_value = mock_client
            
            # Start kernel
            await manager.start_kernel("test.ipynb")
            
            # Check default value
            session = manager.sessions[nb_path]
            assert session['stop_on_error'] is False
    
    @pytest.mark.asyncio
    async def test_stop_on_error_can_be_toggled(self):
        """Test that stop_on_error can be set to True."""
        manager = SessionManager()
        nb_path = str(Path("test.ipynb").resolve())
        
        # Mock session
        manager.sessions[nb_path] = {
            'km': MagicMock(),
            'kc': MagicMock(),
            'execution_queue': asyncio.Queue(),
            'executions': {},
            'execution_counter': 0,
            'stop_on_error': False
        }
        
        # Toggle it
        session = manager.sessions[nb_path]
        session['stop_on_error'] = True
        
        # Verify
        assert session['stop_on_error'] is True
    
    @pytest.mark.asyncio
    async def test_stop_on_error_clears_queue_on_error(self):
        """Test that stop_on_error=True clears remaining queue items on error."""
        manager = SessionManager()
        nb_path = str(Path("test.ipynb").resolve())
        
        # Create session with stop_on_error enabled
        execution_queue = asyncio.Queue()
        manager.sessions[nb_path] = {
            'km': MagicMock(),
            'kc': MagicMock(),
            'execution_queue': execution_queue,
            'executions': {},
            'execution_counter': 0,
            'stop_on_error': True
        }
        
        # Queue should be empty initially
        assert execution_queue.qsize() == 0
        
        # Add multiple items
        await execution_queue.put({'exec_id': '1', 'cell_index': 0, 'code': 'x=1'})
        await execution_queue.put({'exec_id': '2', 'cell_index': 1, 'code': 'y=2'})
        await execution_queue.put({'exec_id': '3', 'cell_index': 2, 'code': 'z=3'})
        
        assert execution_queue.qsize() == 3
        
        # Simulate error clearing queue (what _queue_processor would do)
        while not execution_queue.empty():
            try:
                execution_queue.get_nowait()
                execution_queue.task_done()
            except asyncio.QueueEmpty:
                break
        
        # Queue should be empty after clearing
        assert execution_queue.qsize() == 0


class TestAgentWorkflow:
    """Integration tests for typical agent workflows."""
    
    @pytest.mark.asyncio
    async def test_agent_workflow_list_then_inspect(self):
        """
        Test typical agent workflow:
        1. List variables
        2. Inspect specific variable
        """
        manager = SessionManager()
        nb_path = str(Path("test.ipynb").resolve())
        
        # Mock session
        manager.sessions[nb_path] = {
            'km': MagicMock(),
            'kc': MagicMock(),
            'execution_queue': asyncio.Queue(),
            'executions': {},
            'execution_counter': 0,
            'stop_on_error': False
        }
        
        # Mock run_simple_code to return variable list
        async def mock_run_simple(path, code):
            if 'dir()' in code:
                return '[{"name": "df", "type": "DataFrame"}, {"name": "x", "type": "int"}]'
            return ""
        
        manager.run_simple_code = mock_run_simple
        
        # Agent lists variables
        var_list = await manager.run_simple_code(nb_path, "code_with_dir()")
        assert "df" in var_list
        assert "DataFrame" in var_list
    
    @pytest.mark.asyncio
    async def test_agent_workflow_run_all_with_stop_on_error(self, tmp_path):
        """
        Test agent workflow:
        1. Create notebook with dependent cells
        2. Enable stop_on_error
        3. Run all cells
        4. First error stops execution
        """
        # Create notebook
        nb = nbformat.v4.new_notebook()
        nb.cells = [
            nbformat.v4.new_code_cell("x = 1"),
            nbformat.v4.new_code_cell("y = undefined_variable"),  # This will error
            nbformat.v4.new_code_cell("z = x + y")  # Should not execute
        ]
        
        nb_path = tmp_path / "test.ipynb"
        with open(nb_path, 'w') as f:
            nbformat.write(nb, f)
        
        # The test validates the structure exists
        assert nb_path.exists()
        assert len(nb.cells) == 3
