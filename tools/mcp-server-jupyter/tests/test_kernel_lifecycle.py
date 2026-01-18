"""
Unit Tests for KernelLifecycle
================================

Phase 2.1: Tests for the extracted kernel process management component.

Tests cover:
- Kernel startup (local, venv, Docker)
- Kernel shutdown
- Kernel restart
- Interrupt handling
- Health checks
- Concurrency limits
- Security validation
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src.kernel_lifecycle import KernelLifecycle


@pytest.fixture
def lifecycle():
    """Create KernelLifecycle instance for testing."""
    return KernelLifecycle(max_concurrent=3)


@pytest.fixture
def temp_notebook_dir(tmp_path):
    """Create temporary notebook directory."""
    nb_dir = tmp_path / "notebooks"
    nb_dir.mkdir()
    return nb_dir


class TestKernelLifecycleBasics:
    """Test basic lifecycle operations."""
    
    def test_initialization(self, lifecycle):
        """Test KernelLifecycle initializes correctly."""
        assert lifecycle.max_concurrent == 3
        assert len(lifecycle.active_kernels) == 0
    
    def test_list_active_kernels_empty(self, lifecycle):
        """Test listing kernels when none are active."""
        assert lifecycle.list_active_kernels() == []
    
    def test_get_kernel_info_not_found(self, lifecycle):
        """Test getting info for non-existent kernel."""
        assert lifecycle.get_kernel_info("nonexistent") is None


class TestSecurityValidation:
    """Test security validation for mount paths."""
    
    def test_validate_mount_path_home_allowed(self, lifecycle):
        """Test that paths under HOME are allowed."""
        home_path = Path.home() / "projects" / "test"
        validated = lifecycle._validate_mount_path(home_path)
        assert validated.is_absolute()
    
    def test_validate_mount_path_root_blocked(self, lifecycle):
        """Test that root directory is blocked."""
        with pytest.raises(ValueError, match="SECURITY VIOLATION"):
            lifecycle._validate_mount_path(Path('/'))
    
    def test_validate_mount_path_etc_blocked(self, lifecycle):
        """Test that /etc is blocked."""
        with pytest.raises(ValueError, match="SECURITY VIOLATION"):
            lifecycle._validate_mount_path(Path('/etc'))
    
    def test_validate_mount_path_sys_blocked(self, lifecycle):
        """Test that system paths are blocked."""
        for dangerous in ['/bin', '/usr', '/var', '/sys', '/boot']:
            with pytest.raises(ValueError, match="SECURITY VIOLATION"):
                lifecycle._validate_mount_path(Path(dangerous))
    
    def test_validate_mount_path_outside_allowed_base(self, lifecycle):
        """Test that paths outside allowed base are blocked."""
        # Try to mount /opt (outside HOME and /tmp)
        with pytest.raises(ValueError, match="Security Violation|SECURITY VIOLATION"):
            lifecycle._validate_mount_path(Path('/opt'))


class TestDockerConfiguration:
    """Test Docker kernel configuration."""
    
    def test_configure_docker_kernel_basic(self, lifecycle, temp_notebook_dir):
        """Test basic Docker configuration."""
        cmd, env, env_name = lifecycle._configure_docker_kernel(
            docker_image="python:3.11",
            notebook_dir=temp_notebook_dir,
            connection_file="/tmp/kernel.json"
        )
        
        assert isinstance(cmd, list)
        assert 'docker' in cmd
        assert 'run' in cmd
        assert 'python:3.11' in cmd
        assert '--network' in cmd
        assert 'none' in cmd
        assert '--read-only' in cmd
        assert '--memory' in cmd
        assert '4g' in cmd
        assert env_name == "docker:python:3.11"
    
    def test_configure_docker_kernel_creates_sandbox(self, lifecycle, temp_notebook_dir):
        """Test that Docker config creates sandbox directory."""
        cmd, env, env_name = lifecycle._configure_docker_kernel(
            docker_image="python:3.11",
            notebook_dir=temp_notebook_dir,
            connection_file="/tmp/kernel.json"
        )
        
        # Check sandbox was created
        sandbox_dir = temp_notebook_dir / ".mcp_sandbox"
        assert sandbox_dir.exists()
        assert sandbox_dir.is_dir()


class TestLocalKernelConfiguration:
    """Test local Python kernel configuration."""
    
    def test_configure_local_kernel_system_python(self, lifecycle):
        """Test configuration with system Python."""
        py_exe, env_name, kernel_env = lifecycle._configure_local_kernel()
        
        assert py_exe is not None
        assert env_name == "system"
        assert 'MCP_KERNEL_ID' in kernel_env
        assert len(kernel_env['MCP_KERNEL_ID']) == 36  # UUID length
    
    def test_configure_local_kernel_venv(self, lifecycle, tmp_path):
        """Test configuration with virtual environment."""
        # Create fake venv structure
        venv_dir = tmp_path / "test_venv"
        venv_dir.mkdir()
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        python_exe = bin_dir / "python"
        python_exe.touch()
        python_exe.chmod(0o755)
        
        py_exe, env_name, kernel_env = lifecycle._configure_local_kernel(
            venv_path=str(venv_dir)
        )
        
        assert str(venv_dir) in py_exe
        assert env_name == f"venv:{venv_dir.name}"
        assert 'MCP_KERNEL_ID' in kernel_env
    
    def test_configure_local_kernel_nonexistent_venv(self, lifecycle):
        """Test graceful fallback when venv doesn't exist."""
        py_exe, env_name, kernel_env = lifecycle._configure_local_kernel(
            venv_path="/nonexistent/venv"
        )
        
        # Should fall back to system Python
        assert env_name == "system"


@pytest.mark.asyncio
class TestKernelStartup:
    """Test kernel startup operations."""
    
    async def test_start_kernel_exceeds_limit(self, lifecycle, temp_notebook_dir):
        """Test that starting too many kernels raises error."""
        # Mock the actual kernel start to avoid real process
        with patch('src.kernel_lifecycle.AsyncKernelManager') as mock_km_class:
            mock_km = AsyncMock()
            mock_km_class.return_value = mock_km
            mock_km.start_kernel = AsyncMock()
            
            # Start max_concurrent kernels
            for i in range(lifecycle.max_concurrent):
                await lifecycle.start_kernel(
                    kernel_id=f"kernel_{i}",
                    notebook_dir=temp_notebook_dir
                )
            
            # Try to start one more
            with pytest.raises(RuntimeError, match="Maximum concurrent kernels"):
                await lifecycle.start_kernel(
                    kernel_id="kernel_overflow",
                    notebook_dir=temp_notebook_dir
                )
    
    async def test_start_kernel_tracks_metadata(self, lifecycle, temp_notebook_dir):
        """Test that kernel metadata is tracked correctly."""
        with patch('src.kernel_lifecycle.AsyncKernelManager') as mock_km_class:
            mock_km = AsyncMock()
            mock_km_class.return_value = mock_km
            mock_km.start_kernel = AsyncMock()
            
            kernel_id = "test_kernel"
            await lifecycle.start_kernel(
                kernel_id=kernel_id,
                notebook_dir=temp_notebook_dir
            )
            
            # Check metadata
            info = lifecycle.get_kernel_info(kernel_id)
            assert info is not None
            assert info['notebook_dir'] == str(temp_notebook_dir)
            assert info['env_name'] == 'system'
            assert 'started_at' in info


@pytest.mark.asyncio
class TestKernelShutdown:
    """Test kernel shutdown operations."""
    
    async def test_stop_kernel_success(self, lifecycle, temp_notebook_dir):
        """Test successful kernel shutdown."""
        with patch('src.kernel_lifecycle.AsyncKernelManager') as mock_km_class:
            mock_km = AsyncMock()
            mock_km_class.return_value = mock_km
            mock_km.start_kernel = AsyncMock()
            mock_km.shutdown_kernel = AsyncMock()
            
            kernel_id = "test_kernel"
            await lifecycle.start_kernel(kernel_id, temp_notebook_dir)
            
            # Stop the kernel
            success = await lifecycle.stop_kernel(kernel_id)
            
            assert success is True
            assert kernel_id not in lifecycle.active_kernels
            mock_km.shutdown_kernel.assert_called_once()
    
    async def test_stop_kernel_not_found(self, lifecycle):
        """Test stopping non-existent kernel."""
        success = await lifecycle.stop_kernel("nonexistent")
        assert success is False


@pytest.mark.asyncio
class TestKernelRestart:
    """Test kernel restart operations."""
    
    async def test_restart_kernel_success(self, lifecycle, temp_notebook_dir):
        """Test successful kernel restart."""
        with patch('src.kernel_lifecycle.AsyncKernelManager') as mock_km_class:
            mock_km = AsyncMock()
            mock_km_class.return_value = mock_km
            mock_km.start_kernel = AsyncMock()
            mock_km.restart_kernel = AsyncMock()
            
            kernel_id = "test_kernel"
            await lifecycle.start_kernel(kernel_id, temp_notebook_dir)
            
            # Restart the kernel
            success = await lifecycle.restart_kernel(kernel_id)
            
            assert success is True
            mock_km.restart_kernel.assert_called_once()
    
    async def test_restart_kernel_not_found(self, lifecycle):
        """Test restarting non-existent kernel."""
        success = await lifecycle.restart_kernel("nonexistent")
        assert success is False


@pytest.mark.asyncio
class TestKernelInterrupt:
    """Test kernel interrupt operations."""
    
    async def test_interrupt_kernel_success(self, lifecycle, temp_notebook_dir):
        """Test successful kernel interrupt."""
        with patch('src.kernel_lifecycle.AsyncKernelManager') as mock_km_class:
            mock_km = AsyncMock()
            mock_km_class.return_value = mock_km
            mock_km.start_kernel = AsyncMock()
            mock_km.interrupt_kernel = AsyncMock()
            
            kernel_id = "test_kernel"
            await lifecycle.start_kernel(kernel_id, temp_notebook_dir)
            
            # Interrupt the kernel
            success = await lifecycle.interrupt_kernel(kernel_id)
            
            assert success is True
            mock_km.interrupt_kernel.assert_called_once()
    
    async def test_interrupt_kernel_not_found(self, lifecycle):
        """Test interrupting non-existent kernel."""
        success = await lifecycle.interrupt_kernel("nonexistent")
        assert success is False


@pytest.mark.asyncio
class TestHealthCheck:
    """Test kernel health monitoring."""
    
    async def test_health_check_alive(self, lifecycle, temp_notebook_dir):
        """Test health check for alive kernel."""
        with patch('src.kernel_lifecycle.AsyncKernelManager') as mock_km_class:
            mock_km = AsyncMock()
            mock_client = Mock()  # Client itself is not async, just client() method
            mock_km_class.return_value = mock_km
            mock_km.start_kernel = AsyncMock()
            # client() method returns the mock client (not async once called)
            mock_km.client = Mock(return_value=mock_client)
            # is_alive() is synchronous
            mock_client.is_alive = Mock(return_value=True)
            mock_client.kernel_info = AsyncMock(return_value={'status': 'ok'})
            
            kernel_id = "test_kernel"
            await lifecycle.start_kernel(kernel_id, temp_notebook_dir)
            
            # Health check
            result = await lifecycle.health_check(kernel_id)
            
            assert result['alive'] is True
            assert 'latency_ms' in result
    
    async def test_health_check_not_found(self, lifecycle):
        """Test health check for non-existent kernel."""
        result = await lifecycle.health_check("nonexistent")
        assert result['alive'] is False
        assert 'error' in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
