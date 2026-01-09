"""
Pytest configuration and fixtures for MCP Jupyter Server tests.
"""

import pytest
import tempfile
import shutil
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock
import nbformat
import sys


@pytest.fixture
def tmp_notebook_dir(tmp_path):
    """Creates a temporary directory for notebook tests."""
    notebook_dir = tmp_path / "notebooks"
    notebook_dir.mkdir()
    return notebook_dir


@pytest.fixture
def create_test_notebook(tmp_notebook_dir):
    """
    Factory fixture that creates test notebooks with specified content.
    
    Usage:
        def test_something(create_test_notebook):
            nb_path = create_test_notebook("test.ipynb", cells=[
                {"type": "code", "source": "print('hello')"},
                {"type": "markdown", "source": "# Header"}
            ])
    """
    def _create_notebook(filename, cells=None, metadata=None):
        """
        Creates a test notebook.
        
        Args:
            filename: Name of the notebook file
            cells: List of dicts with 'type' and 'source' keys
            metadata: Optional notebook metadata dict
        
        Returns:
            Path to created notebook
        """
        nb_path = tmp_notebook_dir / filename
        nb = nbformat.v4.new_notebook()
        
        # Add default metadata
        nb.metadata['kernelspec'] = {
            'name': 'python3',
            'display_name': 'Python 3',
            'language': 'python'
        }
        nb.metadata['language_info'] = {
            'name': 'python',
            'version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        }
        
        # Update with custom metadata if provided
        if metadata:
            nb.metadata.update(metadata)
        
        # Add cells if provided
        if cells:
            for cell_spec in cells:
                cell_type = cell_spec.get('type', 'code')
                source = cell_spec.get('source', '')
                
                if cell_type == 'code':
                    cell = nbformat.v4.new_code_cell(source=source)
                elif cell_type == 'markdown':
                    cell = nbformat.v4.new_markdown_cell(source=source)
                elif cell_type == 'raw':
                    cell = nbformat.v4.new_raw_cell(source=source)
                else:
                    cell = nbformat.v4.new_code_cell(source=source)
                
                # Add metadata if provided
                if 'metadata' in cell_spec:
                    cell.metadata.update(cell_spec['metadata'])
                
                nb.cells.append(cell)
        
        # Write notebook to file
        with open(nb_path, 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)
        
        return str(nb_path)
    
    return _create_notebook


@pytest.fixture
def create_test_venv(tmp_path):
    """
    Factory fixture that creates a test virtual environment.
    
    Note: This creates a REAL venv for integration tests.
    For unit tests, use mock_python_executable instead.
    """
    def _create_venv(venv_name="test_venv"):
        """
        Creates a real virtual environment for testing.
        
        Args:
            venv_name: Name of the venv directory
        
        Returns:
            Dict with 'venv_path', 'python_path', 'success'
        """
        venv_path = tmp_path / venv_name
        
        try:
            import subprocess
            result = subprocess.run(
                [sys.executable, '-m', 'venv', str(venv_path)],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                return {
                    'success': False,
                    'venv_path': None,
                    'python_path': None,
                    'error': result.stderr
                }
            
            # Determine Python executable path
            import os
            if os.name == 'nt':
                python_path = venv_path / 'Scripts' / 'python.exe'
            else:
                python_path = venv_path / 'bin' / 'python'
            
            return {
                'success': True,
                'venv_path': str(venv_path),
                'python_path': str(python_path),
                'error': None
            }
        except Exception as e:
            return {
                'success': False,
                'venv_path': None,
                'python_path': None,
                'error': str(e)
            }
    
    return _create_venv


@pytest.fixture
def mock_kernel_manager():
    """
    Creates a mocked AsyncKernelManager for unit tests.
    """
    mock_km = AsyncMock()
    mock_km.has_kernel = True
    mock_km.kernel = Mock()
    mock_km.kernel.pid = 12345
    mock_km.kernel_cmd = [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
    
    # Mock start_kernel to return immediately
    async def mock_start_kernel(**kwargs):
        pass
    mock_km.start_kernel = mock_start_kernel
    
    # Mock shutdown_kernel
    async def mock_shutdown_kernel(**kwargs):
        pass
    mock_km.shutdown_kernel = mock_shutdown_kernel
    
    # Mock interrupt_kernel
    async def mock_interrupt_kernel(**kwargs):
        pass
    mock_km.interrupt_kernel = mock_interrupt_kernel
    
    # Mock restart_kernel
    async def mock_restart_kernel(**kwargs):
        pass
    mock_km.restart_kernel = mock_restart_kernel
    
    return mock_km


@pytest.fixture
def mock_kernel_client():
    """
    Creates a mocked kernel client that simulates message flow.
    """
    mock_kc = Mock()
    mock_kc._iopub_channel = asyncio.Queue()
    mock_kc._msg_id_counter = 0
    mock_kc._pending_messages = {}
    
    def mock_execute(code, silent=False, store_history=True, **kwargs):
        """Mock execute that generates a message ID."""
        mock_kc._msg_id_counter += 1
        msg_id = f"msg_{mock_kc._msg_id_counter}"
        mock_kc._pending_messages[msg_id] = code
        return msg_id
    
    mock_kc.execute = mock_execute
    
    async def mock_get_iopub_msg(timeout=None):
        """Mock get_iopub_msg that returns simulated messages."""
        try:
            msg = await asyncio.wait_for(
                mock_kc._iopub_channel.get(),
                timeout=timeout if timeout else None
            )
            return msg
        except asyncio.TimeoutError:
            raise TimeoutError("Timed out waiting for IOPub message")
    
    mock_kc.get_iopub_msg = mock_get_iopub_msg
    
    def mock_start_channels():
        """Mock start_channels."""
        pass
    
    mock_kc.start_channels = mock_start_channels
    
    def mock_stop_channels():
        """Mock stop_channels."""
        pass
    
    mock_kc.stop_channels = mock_stop_channels
    
    async def mock_wait_for_ready(timeout=60):
        """Mock wait_for_ready."""
        pass
    
    mock_kc.wait_for_ready = mock_wait_for_ready
    
    # Helper to simulate execution results
    async def simulate_execution(msg_id, outputs=None, error=None):
        """
        Simulates kernel execution by posting IOPub messages.
        
        Args:
            msg_id: Message ID to simulate
            outputs: List of output dicts (text, data, etc.)
            error: Optional error dict with ename, evalue, traceback
        """
        # Status: busy
        await mock_kc._iopub_channel.put({
            'msg_type': 'status',
            'parent_header': {'msg_id': msg_id},
            'content': {'execution_state': 'busy'}
        })
        
        # Execute_input
        await mock_kc._iopub_channel.put({
            'msg_type': 'execute_input',
            'parent_header': {'msg_id': msg_id},
            'content': {
                'code': mock_kc._pending_messages.get(msg_id, ''),
                'execution_count': 1
            }
        })
        
        # Outputs
        if outputs:
            for output in outputs:
                if output.get('type') == 'stream':
                    await mock_kc._iopub_channel.put({
                        'msg_type': 'stream',
                        'parent_header': {'msg_id': msg_id},
                        'content': {
                            'name': output.get('name', 'stdout'),
                            'text': output.get('text', '')
                        }
                    })
                elif output.get('type') == 'execute_result':
                    await mock_kc._iopub_channel.put({
                        'msg_type': 'execute_result',
                        'parent_header': {'msg_id': msg_id},
                        'content': {
                            'data': output.get('data', {}),
                            'metadata': output.get('metadata', {}),
                            'execution_count': 1
                        }
                    })
        
        # Error if provided
        if error:
            await mock_kc._iopub_channel.put({
                'msg_type': 'error',
                'parent_header': {'msg_id': msg_id},
                'content': {
                    'ename': error.get('ename', 'Error'),
                    'evalue': error.get('evalue', 'An error occurred'),
                    'traceback': error.get('traceback', ['Error traceback'])
                }
            })
        
        # Status: idle
        await mock_kc._iopub_channel.put({
            'msg_type': 'status',
            'parent_header': {'msg_id': msg_id},
            'content': {'execution_state': 'idle'}
        })
    
    mock_kc.simulate_execution = simulate_execution
    
    return mock_kc


@pytest.fixture
def mock_python_executable(tmp_path):
    """
    Creates a mock Python executable for environment detection tests.
    """
    def _create_mock_exe(env_type="venv", env_name="test_env"):
        """
        Creates a mock Python executable structure.
        
        Args:
            env_type: Type of environment (venv, conda, system)
            env_name: Name of the environment
        
        Returns:
            Path to mock executable
        """
        if env_type == "venv":
            env_path = tmp_path / env_name
            env_path.mkdir(exist_ok=True)
            
            import os
            if os.name == 'nt':
                scripts_dir = env_path / 'Scripts'
                scripts_dir.mkdir(exist_ok=True)
                python_exe = scripts_dir / 'python.exe'
            else:
                bin_dir = env_path / 'bin'
                bin_dir.mkdir(exist_ok=True)
                python_exe = bin_dir / 'python'
            
            # Create empty file
            python_exe.touch()
            
            # Create pyvenv.cfg
            (env_path / 'pyvenv.cfg').write_text(
                f"home = {sys.prefix}\n"
                f"include-system-site-packages = false\n"
                f"version = {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n"
            )
            
            return str(python_exe)
        
        elif env_type == "conda":
            env_path = tmp_path / 'miniconda3' / 'envs' / env_name
            env_path.mkdir(parents=True, exist_ok=True)
            
            import os
            if os.name == 'nt':
                python_exe = env_path / 'python.exe'
            else:
                bin_dir = env_path / 'bin'
                bin_dir.mkdir(exist_ok=True)
                python_exe = bin_dir / 'python'
            
            python_exe.touch()
            return str(python_exe)
        
        else:  # system
            return sys.executable
    
    return _create_mock_exe


# Event loop fixture for async tests
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    # Fix for Windows: Use WindowsSelectorEventLoopPolicy to avoid zmq warning
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
