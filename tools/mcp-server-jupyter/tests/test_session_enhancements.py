import pytest
from unittest.mock import MagicMock, patch
import os
import sys
from pathlib import Path
from src.session import _get_activated_env_vars, SessionManager

class TestEnvironmentActivation:
    """Test the improved Conda/Venv activation logic."""

    @patch('src.environment.Path')
    @patch('src.environment.os')
    def test_conda_activation_linux(self, mock_os, mock_path):
        """Test conda activation variables on Linux."""
        # Setup Mocks
        mock_os.name = 'posix'
        mock_os.environ = {'PATH': '/usr/bin'}
        mock_os.pathsep = ':'
        
        # Mock Path structure
        venv_path = MagicMock()
        venv_path.resolve.return_value = venv_path
        venv_path.__str__.return_value = "/opt/conda/envs/myenv"
        venv_path.name = "myenv"
        
        # Emulate conda-meta existence
        conda_meta = MagicMock()
        conda_meta.exists.return_value = True
        
        # When path / "conda-meta" is called
        def path_truediv(other):
            if other == "conda-meta": 
                return conda_meta
            return MagicMock() # generic child
            
        venv_path.__truediv__.side_effect = path_truediv
        
        # Fix mock for Path(python_exe).parent
        # The code does: bin_dir = str(Path(python_exe).parent)
        python_exe_path = MagicMock()
        parent_path = MagicMock()
        parent_path.__str__.return_value = "/opt/conda/envs/myenv/bin"
        python_exe_path.parent = parent_path

        def path_side_effect(arg):
            if arg == "/opt/conda/envs/myenv/bin/python":
                return python_exe_path
            return venv_path

        mock_path.side_effect = path_side_effect
        
        # Execute
        env = _get_activated_env_vars("/opt/conda/envs/myenv", "/opt/conda/envs/myenv/bin/python")
        
        # Verify
        assert env['CONDA_PREFIX'] == "/opt/conda/envs/myenv"
        assert env['CONDA_DEFAULT_ENV'] == "myenv"
        assert "/opt/conda/envs/myenv/bin" in env['PATH']

    @patch('src.environment.Path')
    @patch('src.environment.os')
    def test_conda_activation_windows(self, mock_os, mock_path):
        """Test conda activation variables on Windows (DLL handling)."""
        # Setup Mocks
        mock_os.name = 'nt'
        mock_os.environ = {'PATH': r'C:\Windows'}
        mock_os.pathsep = ';'
        
        # Mock Path structure
        venv_path = MagicMock()
        venv_path.resolve.return_value = venv_path
        venv_path.__str__.return_value = r"C:\conda\envs\myenv"
        venv_path.name = "myenv"
        
        # Emulate conda-meta existence (It is a conda env)
        conda_meta = MagicMock()
        conda_meta.exists.return_value = True
        
        # Mock children existence (Scripts, Library/bin)
        scripts = MagicMock()
        scripts.exists.return_value = True
        scripts.__str__.return_value = r"C:\conda\envs\myenv\Scripts"
        
        lib_bin = MagicMock()
        lib_bin.exists.return_value = True
        lib_bin.__str__.return_value = r"C:\conda\envs\myenv\Library\bin"
        
        # Handle the chained / operator
        def path_truediv(other):
            if other == "conda-meta": return conda_meta
            if other == "Scripts": return scripts
            if other == "Library":
                 # Return a mock that, when divided by 'bin', returns lib_bin
                 m = MagicMock()
                 m.__truediv__.side_effect = lambda x: lib_bin if x == 'bin' else MagicMock()
                 return m
            return MagicMock()
            
        venv_path.__truediv__.side_effect = path_truediv
        
        # Fix mock for Path(python_exe).parent for Windows
        python_exe_path = MagicMock()
        parent_path = MagicMock()
        parent_path.__str__.return_value = r"C:\conda\envs\myenv" 
        python_exe_path.parent = parent_path

        def path_side_effect(arg):
            if arg == r"C:\conda\envs\myenv\python.exe":
                return python_exe_path
            return venv_path
            
        mock_path.side_effect = path_side_effect
        
        # Execute
        env = _get_activated_env_vars(r"C:\conda\envs\myenv", r"C:\conda\envs\myenv\python.exe")
        
        # Verify
        assert env['CONDA_PREFIX'] == r"C:\conda\envs\myenv"
        # Check that Library/bin and Scripts are in PATH
        assert r"C:\conda\envs\myenv\Library\bin" in env['PATH']
        assert r"C:\conda\envs\myenv\Scripts" in env['PATH']


class TestSessionFeatures:
    """Test resilience features."""
    
    @pytest.mark.asyncio
    async def test_timeout_configuration(self):
        """Verify timeout parameter is stored in session."""
        manager = SessionManager(default_execution_timeout=60)
        assert manager.default_execution_timeout == 60

@pytest.mark.asyncio
async def test_install_package_invalidates_caches():
    """Verify importlib.invalidate_caches() is injected after pip install.
    
    Fixes "Module Not Found" - After successful pip install, the kernel's import
    cache must be invalidated so it sees the newly installed package immediately.
    """
    from src.session import SessionManager
    from unittest.mock import AsyncMock, patch
    
    manager = SessionManager()
    
    # Mock the session parts
    manager.sessions["/tmp/nb.ipynb"] = {
        "km": MagicMock(),
        "kc": MagicMock()
    }
    # Mock kernel command
    manager.sessions["/tmp/nb.ipynb"]["km"].kernel_cmd = ["python"]
    
    # Mock execute_cell_async to verify it receives the invalidation code
    manager.execute_cell_async = AsyncMock()
    
    # Mock subprocess to simulate successful pip install
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"Successfully installed simplejson", b"")
        mock_exec.return_value = mock_proc
        
        result = await manager.install_package("/tmp/nb.ipynb", "simplejson")
        
        # Verify install succeeded
        assert "Successfully installed" in result, f"Install failed: {result}"
        
        # Verify execute_cell_async was called with invalidation code
        calls = manager.execute_cell_async.call_args_list
        assert len(calls) > 0, "execute_cell_async was not called"
        
        # Get the code passed to the call: args[0] = nb_path, args[1] = index, args[2] = code
        code_sent = calls[0][0][2]  # Third positional argument
        assert "importlib.invalidate_caches()" in code_sent, f"Cache invalidation not found in: {code_sent}"
        
        print("✓ Cache invalidation code injected after package install")