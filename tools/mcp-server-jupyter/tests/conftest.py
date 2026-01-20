"""
Pytest configuration and fixtures for MCP Jupyter Server tests.
"""

import pytest
import tempfile
import shutil
import asyncio
import subprocess
import atexit
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock
import nbformat
import sys


def _cleanup_all_kernels():
    """
    Kill all ipykernel processes - called at test session end.
    
    WARNING: In parallel execution (pytest-xdist), this can kill kernels from 
    other test workers. Only use at session end, not before each test.
    """
    # Only run cleanup if NOT in a xdist worker (to avoid killing other workers' kernels)
    import os
    if os.environ.get('PYTEST_XDIST_WORKER'):
        # In parallel mode, don't kill other workers' kernels
        return
    
    try:
        # First try pkill
        subprocess.run(['pkill', '-9', '-f', 'ipykernel_launcher'], 
                      capture_output=True, check=False, timeout=3)
        # Also try killing by pattern match on ps output
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=3)
        for line in result.stdout.splitlines():
            if 'ipykernel_launcher' in line or 'jupyter-kernel' in line:
                parts = line.split()
                if len(parts) > 1:
                    try:
                        pid = int(parts[1])
                        subprocess.run(['kill', '-9', str(pid)], capture_output=True, timeout=1)
                    except (ValueError, subprocess.TimeoutExpired):
                        pass
    except Exception:
        pass


# Register cleanup to run when Python exits (covers pytest-xdist workers)
atexit.register(_cleanup_all_kernels)


@pytest.fixture(scope="session", autouse=True)
def cleanup_kernels_at_session_end():
    """Session-scoped fixture to clean up all kernels when test session ends."""
    yield
    _cleanup_all_kernels()


@pytest.fixture(scope="function", autouse=True)
def cleanup_kernels_before_test():
    """
    Function-scoped fixture to clean up kernels before each test.
    
    DISABLED IN PARALLEL MODE: In pytest-xdist parallel execution, killing
    all kernels would affect other test workers. Instead, each test should
    properly clean up its own resources.
    """
    import os
    import time
    
    # Skip aggressive cleanup in parallel mode
    if os.environ.get('PYTEST_XDIST_WORKER'):
        yield
        return
    
    # Only in sequential mode: Run cleanup
    _cleanup_all_kernels()
    time.sleep(0.5)
    _cleanup_all_kernels()
    # Give more time for ports to be released
    time.sleep(1.5)
    yield


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


# Asyncio policy fixture (preferred over redefining event_loop)
# See pytest-asyncio deprecation: use event_loop_policy instead of overriding event_loop
@pytest.fixture(scope="session")
def event_loop_policy():
    """Provide an event loop policy without overriding pytest-asyncio's event_loop fixture.

    On Windows, use WindowsSelectorEventLoopPolicy to avoid known zmq compatibility warnings.
    On other platforms, use the default policy.
    """
    import sys
    if sys.platform == 'win32':
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(autouse=True)
def isolate_home(monkeypatch, tmp_path):
    """
    Isolates the HOME directory for each test to prevent side effects 
    and race conditions in parallel execution (pytest-xdist).
    This ensures ~/.mcp-jupyter/sessions is unique per test.
    """
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))


@pytest.fixture(autouse=True)
async def auto_cleanup_session_managers(monkeypatch):
    """
    AUTOMATIC CLEANUP: Tracks all SessionManager instances created during a test
    and cleans them up automatically, even if the test fails or raises an exception.
    
    This is an autouse fixture that runs for EVERY test, providing fail-safe cleanup
    to prevent resource leaks and WSL network corruption.
    
    How it works:
    1. Monkey-patches SessionManager.__init__ to track all instances
    2. After test completes (success or failure), cleans up all tracked instances
    3. Cleans up kernels, channels, tasks, and sessions
    
    Tests don't need to do anything - this runs automatically.
    """
    from src.session import SessionManager
    
    # Track all SessionManager instances created during this test
    tracked_managers = []
    original_init = SessionManager.__init__
    
    def tracking_init(self, *args, **kwargs):
        """Wrapper that tracks SessionManager instances."""
        original_init(self, *args, **kwargs)
        tracked_managers.append(self)
    
    # Monkey-patch the __init__ to track instances
    monkeypatch.setattr(SessionManager, '__init__', tracking_init)
    
    # Let the test run
    yield
    
    # CLEANUP: After test completes (even if it failed), clean up all managers
    for manager in tracked_managers:
        try:
            # Clean up all sessions in this manager
            for nb_path in list(manager.sessions.keys()):
                try:
                    session = manager.sessions[nb_path]
                    
                    # Cancel ALL background tasks first
                    for task_key in ['queue_task', 'iopub_task', 'stdin_task']:
                        if task_key in session:
                            try:
                                session[task_key].cancel()
                            except Exception:
                                pass
                    
                    # Close kernel client channels
                    if 'kc' in session and hasattr(session['kc'], 'stop_channels'):
                        try:
                            result = session['kc'].stop_channels()
                            # Handle AsyncMock which returns a coroutine
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            pass
                    
                    # Stop kernel manager (force immediate shutdown)
                    if 'km' in session and hasattr(session['km'], 'shutdown_kernel'):
                        try:
                            await session['km'].shutdown_kernel(now=True)
                        except Exception:
                            pass
                except Exception:
                    pass
            
            # Clear all sessions
            manager.sessions.clear()
        except Exception:
            # Ignore any errors during cleanup
            pass
    
    # Give event loop time to finalize all cancellations
    await asyncio.sleep(0.05)


@pytest.fixture
async def clean_session_manager():
    """
    Provides a SessionManager with proper cleanup to prevent resource leaks.
    
    CRITICAL: Without this, tests leak OS resources (asyncio queues, file descriptors,
    threads) that can corrupt WSL's network stack when running with high parallelism.
    
    Usage:
        async def test_something(clean_session_manager):
            manager = clean_session_manager
            await manager.start_kernel("test.ipynb")
            # ... test code ...
            # Automatic cleanup happens here
    """
    from src.session import SessionManager
    
    manager = SessionManager()
    yield manager
    
    # Cleanup: Stop all kernels and clear sessions
    for nb_path in list(manager.sessions.keys()):
        try:
            # Close kernel client channels if they exist
            session = manager.sessions[nb_path]
            if 'kc' in session and hasattr(session['kc'], 'stop_channels'):
                try:
                    session['kc'].stop_channels()
                except Exception:
                    pass
            
            # Stop kernel manager if it exists
            if 'km' in session and hasattr(session['km'], 'shutdown_kernel'):
                try:
                    await session['km'].shutdown_kernel(now=True)
                except Exception:
                    pass
            
            # Cancel background tasks
            if 'queue_task' in session:
                try:
                    session['queue_task'].cancel()
                    await asyncio.sleep(0)  # Allow cancellation to propagate
                except Exception:
                    pass
        except Exception:
            pass
    
    # Clear all sessions
    manager.sessions.clear()
    
    # Give event loop time to clean up
    await asyncio.sleep(0.01)


@pytest.fixture
def mock_async_kernel_manager():
    """
    Creates a fully-mocked AsyncKernelManager for parallel-safe testing.
    
    This fixture provides a mock that doesn't start real Jupyter kernels,
    making it safe for parallel execution with pytest-xdist.
    
    Usage:
        def test_something(mock_async_kernel_manager, monkeypatch):
            monkeypatch.setattr("src.session.AsyncKernelManager", 
                              lambda: mock_async_kernel_manager)
            # Now SessionManager will use the mock instead of real kernels
    """
    mock_km = AsyncMock()
    mock_km.kernel_id = "test-kernel-id-12345"
    mock_km.has_kernel = True
    mock_km.is_alive = Mock(return_value=True)
    mock_km.kernel = Mock()
    mock_km.kernel.pid = 99999
    mock_km.kernel_cmd = [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
    mock_km.connection_file = "/tmp/kernel-test.json"
    
    # Create a mock kernel client
    mock_kc = AsyncMock()
    mock_kc.start_channels = Mock()
    mock_kc.stop_channels = Mock()  # Return a regular Mock, not AsyncMock
    mock_kc.wait_for_ready = AsyncMock()
    mock_kc.execute = Mock(return_value="msg-12345")
    mock_kc.is_alive = Mock(return_value=True)
    mock_kc.get_iopub_msg = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_kc.get_shell_msg = AsyncMock(return_value={
        'content': {'status': 'ok'},
        'parent_header': {'msg_id': 'msg-12345'}
    })
    
    mock_km.client = Mock(return_value=mock_kc)
    
    return mock_km


@pytest.fixture
def patch_kernel_managers(mock_async_kernel_manager, monkeypatch):
    """
    Patches AsyncKernelManager in BOTH locations to prevent real kernel creation.
    
    This is essential for parallel test execution - without this patch, tests
    will try to start real Jupyter kernels which causes:
    1. Port contention when multiple tests run simultaneously
    2. "Kernel died before replying" errors
    3. Resource exhaustion
    
    Usage:
        async def test_something(patch_kernel_managers):
            # AsyncKernelManager is now mocked everywhere
            from src.session import SessionManager
            manager = SessionManager()
            await manager.start_kernel("test.ipynb")  # Uses mock, no real kernel
    """
    # Create a factory that returns the mock
    def mock_km_factory(*args, **kwargs):
        return mock_async_kernel_manager
    
    # Patch in BOTH locations where AsyncKernelManager might be imported
    monkeypatch.setattr("src.session.AsyncKernelManager", mock_km_factory)
    monkeypatch.setattr("src.kernel_lifecycle.AsyncKernelManager", mock_km_factory)
    
    return mock_async_kernel_manager

