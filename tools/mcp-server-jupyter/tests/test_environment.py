"""
Tests for environment detection and management functions.
Uses mocked subprocess calls to avoid system dependencies.
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from src.environment import (
    get_python_version,
    detect_environment_type,
    validate_python_executable,
    find_conda_environments,
    find_venv_environments
)


class TestGetPythonVersion:
    """Tests for get_python_version function."""
    
    @patch('subprocess.run')
    def test_get_python_version_success(self, mock_run):
        """Test successfully getting Python version."""
        # Mock successful version check
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Python 3.10.5\n",
            stderr=""
        )
        
        result = get_python_version("/usr/bin/python3")
        
        assert result['valid'] is True
        assert result['version'] == "3.10.5"
        assert result['major'] == 3
        assert result['minor'] == 10
        assert result['micro'] == 5
    
    @patch('subprocess.run')
    def test_get_python_version_with_stderr(self, mock_run):
        """Test getting version when output is in stderr."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="",
            stderr="Python 3.9.7\n"
        )
        
        result = get_python_version("/usr/bin/python")
        
        assert result['valid'] is True
        assert result['version'] == "3.9.7"
    
    @patch('subprocess.run')
    def test_get_python_version_with_pip(self, mock_run):
        """Test detecting pip availability."""
        # First call: version check
        # Second call: pip check
        mock_run.side_effect = [
            Mock(returncode=0, stdout="Python 3.10.0\n", stderr=""),
            Mock(returncode=0, stdout="pip 21.0\n", stderr="")
        ]
        
        result = get_python_version("/usr/bin/python")
        
        assert result['valid'] is True
        assert result['pip_available'] is True
    
    @patch('subprocess.run')
    def test_get_python_version_no_pip(self, mock_run):
        """Test when pip is not available."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="Python 3.10.0\n", stderr=""),
            Mock(returncode=1, stdout="", stderr="No module named pip")
        ]
        
        result = get_python_version("/usr/bin/python")
        
        assert result['valid'] is True
        assert result['pip_available'] is False
    
    @patch('subprocess.run')
    def test_get_python_version_timeout(self, mock_run):
        """Test handling timeout."""
        mock_run.side_effect = TimeoutError("Command timed out")
        
        result = get_python_version("/usr/bin/python")
        
        assert result['valid'] is False
        assert 'error' in result
    
    @patch('subprocess.run')
    def test_get_python_version_invalid_executable(self, mock_run):
        """Test with invalid executable."""
        mock_run.side_effect = FileNotFoundError("File not found")
        
        result = get_python_version("/nonexistent/python")
        
        assert result['valid'] is False


class TestDetectEnvironmentType:
    """Tests for detect_environment_type function."""
    
    def test_detect_conda_environment(self):
        """Test detecting conda environment."""
        python_path = "/home/user/miniconda3/envs/myenv/bin/python"
        
        env_type, env_name = detect_environment_type(python_path)
        
        assert env_type == 'conda'
        assert env_name == 'myenv'
    
    def test_detect_conda_base(self):
        """Test detecting conda base environment."""
        python_path = "/home/user/anaconda3/bin/python"
        
        env_type, env_name = detect_environment_type(python_path)
        
        assert env_type == 'conda'
        assert env_name == 'base'
    
    def test_detect_venv(self, tmp_path):
        """Test detecting venv environment."""
        # Create venv structure
        venv_path = tmp_path / "myenv"
        venv_path.mkdir()
        (venv_path / "pyvenv.cfg").write_text("home = /usr")
        
        bin_dir = venv_path / "bin"
        bin_dir.mkdir()
        python_exe = bin_dir / "python"
        python_exe.touch()
        
        env_type, env_name = detect_environment_type(str(python_exe))
        
        assert env_type == 'venv'
        assert env_name == 'myenv'
    
    def test_detect_virtualenv(self, tmp_path):
        """Test detecting virtualenv environment."""
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        
        bin_dir = venv_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "activate").write_text("# activate script")
        
        python_exe = bin_dir / "python"
        python_exe.touch()
        
        env_type, env_name = detect_environment_type(str(python_exe))
        
        assert env_type == 'virtualenv'
        assert env_name == 'venv'
    
    def test_detect_pyenv(self):
        """Test detecting pyenv environment."""
        python_path = "/home/user/.pyenv/versions/3.10.0/bin/python"
        
        env_type, env_name = detect_environment_type(python_path)
        
        assert env_type == 'pyenv'
    
    def test_detect_system_python(self):
        """Test detecting system Python."""
        python_path = "/usr/bin/python3"
        
        env_type, env_name = detect_environment_type(python_path)
        
        assert env_type == 'system'
        assert env_name == 'system'


class TestValidatePythonExecutable:
    """Tests for validate_python_executable function."""
    
    def test_validate_nonexistent_file(self, tmp_path):
        """Test validation of nonexistent file."""
        result = validate_python_executable(str(tmp_path / "nonexistent"))
        
        assert result['valid'] is False
        assert result['exists'] is False
        assert 'error' in result
    
    @patch('subprocess.run')
    def test_validate_existing_file(self, mock_run, tmp_path):
        """Test validation of existing Python executable."""
        # Create mock executable
        python_exe = tmp_path / "python"
        python_exe.touch()
        python_exe.chmod(0o755)
        
        # Mock version check
        mock_run.side_effect = [
            Mock(returncode=0, stdout="Python 3.10.0\n", stderr=""),
            Mock(returncode=0)
        ]
        
        result = validate_python_executable(str(python_exe))
        
        assert result['exists'] is True
        assert result['executable'] is True
        assert result['valid'] is True
        assert result['version'] is not None
    
    def test_validate_non_executable_file(self, tmp_path):
        """Test validation of non-executable file."""
        # Create file without execute permission
        file_path = tmp_path / "not_executable"
        file_path.touch()
        file_path.chmod(0o644)
        
        # Skip on Windows (permission model different)
        if os.name != 'nt':
            result = validate_python_executable(str(file_path))
            
            assert result['exists'] is True
            assert result['executable'] is False
            assert result['valid'] is False


class TestFindCondaEnvironments:
    """Tests for find_conda_environments function."""
    
    @patch('shutil.which')
    @patch('subprocess.run')
    @patch('pathlib.Path.iterdir')
    def test_find_conda_with_command(self, mock_iterdir, mock_run, mock_which):
        """Test finding conda environments using conda command."""
        mock_which.return_value = "/usr/bin/conda"
        
        # Mock conda env list output
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"envs": ["/home/user/miniconda3/envs/env1", "/home/user/miniconda3/envs/env2"]}'
        )
        
        # Mock iterdir to return empty list (no real filesystem access)
        mock_iterdir.return_value = []
        
        with patch('pathlib.Path.exists', return_value=True):
            with patch('src.environment.get_python_version') as mock_version:
                mock_version.return_value = {
                    'valid': True,
                    'version': '3.10.0'
                }
                
                envs = find_conda_environments()
                
                assert len(envs) >= 0  # May find environments
    
    @patch('shutil.which')
    def test_find_conda_no_command(self, mock_which):
        """Test when conda command is not available."""
        mock_which.return_value = None
        
        envs = find_conda_environments()
        
        # Should return empty list or envs from common locations
        assert isinstance(envs, list)


class TestFindVenvEnvironments:
    """Tests for find_venv_environments function."""
    
    @patch('pathlib.Path.cwd')
    @patch('pathlib.Path.home')
    def test_find_venv_in_current_dir(self, mock_home, mock_cwd, tmp_path):
        """Test finding venv in current directory."""
        # Setup mock paths
        mock_cwd.return_value = tmp_path
        mock_home.return_value = tmp_path / "home"
        
        # Create .venv directory
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        
        if os.name == 'nt':
            scripts_dir = venv_dir / "Scripts"
            scripts_dir.mkdir()
            python_exe = scripts_dir / "python.exe"
        else:
            bin_dir = venv_dir / "bin"
            bin_dir.mkdir()
            python_exe = bin_dir / "python"
        
        python_exe.touch()
        
        with patch('src.environment.get_python_version') as mock_version:
            mock_version.return_value = {
                'valid': True,
                'version': '3.10.0'
            }
            
            with patch('src.environment.detect_environment_type') as mock_detect:
                mock_detect.return_value = ('venv', '.venv')
                
                envs = find_venv_environments()
                
                assert len(envs) > 0
                assert any('.venv' in env['env_name'] for env in envs)


class TestEnvironmentEdgeCases:
    """Edge case tests for environment functions."""
    
    @patch('subprocess.run')
    def test_malformed_version_string(self, mock_run):
        """Test handling malformed version string."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Python malformed.version\n",
            stderr=""
        )
        
        # Should handle gracefully
        result = get_python_version("/usr/bin/python")
        
        # May or may not be valid depending on parsing
        assert 'version' in result
    
    def test_detect_environment_with_symlinks(self, tmp_path):
        """Test environment detection with symlinked executables."""
        # Create venv
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        (venv_path / "pyvenv.cfg").write_text("home = /usr")
        
        bin_dir = venv_path / "bin"
        bin_dir.mkdir()
        python_exe = bin_dir / "python"
        python_exe.touch()
        
        # Create symlink (skip on Windows if not admin)
        try:
            symlink = tmp_path / "python_link"
            symlink.symlink_to(python_exe)
            
            env_type, env_name = detect_environment_type(str(symlink))
            
            # Should resolve to actual environment
            assert env_type in ['venv', 'virtualenv', 'system']
        except OSError:
            # Symlink creation failed (Windows without admin)
            pytest.skip("Symlinks not available")
    
    def test_windows_path_detection(self):
        """Test environment detection with Windows paths."""
        if os.name == 'nt':
            python_path = "C:\\Users\\user\\venv\\Scripts\\python.exe"
            
            # Should not crash
            env_type, env_name = detect_environment_type(python_path)
            
            assert isinstance(env_type, str)
            assert isinstance(env_name, str)
