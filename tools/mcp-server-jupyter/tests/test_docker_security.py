"""
Unit Tests for Phase 3.2: Docker Security Profiles
===================================================

Tests for production-grade container security:
- Seccomp profiles
- Capability dropping
- ulimits (resource constraints)
- Read-only root filesystem
- Network isolation
- Security validation

Author: MCP Jupyter Server Team
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src.docker_security import (
    SecureDockerConfig,
    create_custom_seccomp_profile,
    get_default_config,
    get_permissive_config,
)


class TestSecureDockerConfig:
    """Test SecureDockerConfig dataclass."""
    
    def test_default_configuration(self):
        """Test default security configuration."""
        config = SecureDockerConfig()
        
        assert config.seccomp_profile == "default"
        assert config.read_only_rootfs is True
        assert config.network_mode == "none"
        assert config.capabilities_drop == ["ALL"]
        assert "CHOWN" in config.capabilities_add
        # Note: SETUID/SETGID were removed for security - only added via MCP_ALLOW_PRIVILEGE_ESCALATION=1
        assert config.ulimits["nofile"] == (1024, 1024)
        assert config.ulimits["nproc"] == (512, 512)
        assert config.memory_limit == "4g"
    
    def test_to_docker_args_seccomp(self):
        """Test seccomp profile conversion to Docker args."""
        config = SecureDockerConfig(seccomp_profile="default")
        args = config.to_docker_args()
        
        assert '--security-opt' in args
        seccomp_idx = args.index('--security-opt')
        assert 'seccomp=default' in args[seccomp_idx + 1]
    
    def test_to_docker_args_read_only(self):
        """Test read-only root filesystem flag."""
        config = SecureDockerConfig(read_only_rootfs=True)
        args = config.to_docker_args()
        
        assert '--read-only' in args
    
    def test_to_docker_args_network_isolation(self):
        """Test network isolation mode."""
        config = SecureDockerConfig(network_mode="none")
        args = config.to_docker_args()
        
        assert '--network' in args
        network_idx = args.index('--network')
        assert args[network_idx + 1] == 'none'
    
    def test_to_docker_args_capabilities(self):
        """Test capability dropping and adding."""
        config = SecureDockerConfig(
            capabilities_drop=["ALL"],
            capabilities_add=["CHOWN", "SETUID"]
        )
        args = config.to_docker_args()
        
        # Check drop ALL
        assert '--cap-drop' in args
        cap_drop_idx = args.index('--cap-drop')
        assert args[cap_drop_idx + 1] == 'ALL'
        
        # Check add CHOWN
        assert '--cap-add' in args
        cap_add_indices = [i for i, x in enumerate(args) if x == '--cap-add']
        assert len(cap_add_indices) >= 2  # At least CHOWN and SETUID
        
        # Verify CHOWN and SETUID are added
        added_caps = []
        for idx in cap_add_indices:
            if idx + 1 < len(args):
                added_caps.append(args[idx + 1])
        assert 'CHOWN' in added_caps
        assert 'SETUID' in added_caps
    
    def test_to_docker_args_ulimits(self):
        """Test ulimits resource constraints."""
        config = SecureDockerConfig(
            ulimits={
                "nofile": (1024, 1024),
                "nproc": (512, 512),
            }
        )
        args = config.to_docker_args()
        
        assert '--ulimit' in args
        ulimit_indices = [i for i, x in enumerate(args) if x == '--ulimit']
        
        # Check nofile limit
        ulimit_values = [args[i + 1] for i in ulimit_indices if i + 1 < len(args)]
        assert any('nofile=1024:1024' in v for v in ulimit_values)
        assert any('nproc=512:512' in v for v in ulimit_values)
    
    def test_to_docker_args_memory_limit(self):
        """Test memory limit."""
        config = SecureDockerConfig(memory_limit="4g")
        args = config.to_docker_args()
        
        assert '--memory' in args
        memory_idx = args.index('--memory')
        assert args[memory_idx + 1] == '4g'
    
    def test_to_docker_args_tmpfs_mounts(self):
        """Test tmpfs mounts for writable directories."""
        config = SecureDockerConfig()
        args = config.to_docker_args()
        
        assert '--tmpfs' in args
        tmpfs_indices = [i for i, x in enumerate(args) if x == '--tmpfs']
        assert len(tmpfs_indices) >= 1
        
        # Check /tmp mount
        tmpfs_values = [args[i + 1] for i in tmpfs_indices if i + 1 < len(args)]
        assert any('/tmp:rw,noexec,nosuid,size=1g' in v for v in tmpfs_values)
    
    def test_to_docker_args_no_new_privileges(self):
        """Test no-new-privileges security flag."""
        config = SecureDockerConfig()
        args = config.to_docker_args()
        
        assert '--security-opt' in args
        security_indices = [i for i, x in enumerate(args) if x == '--security-opt']
        security_values = [args[i + 1] for i in security_indices if i + 1 < len(args)]
        assert 'no-new-privileges' in security_values
    
    def test_to_docker_args_init_flag(self):
        """Test --init flag for proper signal handling."""
        config = SecureDockerConfig()
        args = config.to_docker_args()
        
        assert '--init' in args


class TestConfigValidation:
    """Test security configuration validation."""
    
    def test_validate_default_config(self):
        """Test validation passes for default config."""
        config = SecureDockerConfig()
        config.validate()  # Should not raise
    
    def test_validate_warns_on_unconfined_seccomp(self):
        """Test validation warns when seccomp is disabled."""
        config = SecureDockerConfig(seccomp_profile="unconfined")
        
        with patch('src.docker_security.logger.warning') as mock_warning:
            config.validate()
            mock_warning.assert_called()
            assert "Seccomp is DISABLED" in str(mock_warning.call_args)
    
    def test_validate_warns_on_host_network(self):
        """Test validation warns when network is host mode."""
        config = SecureDockerConfig(network_mode="host")
        
        with patch('src.docker_security.logger.warning') as mock_warning:
            config.validate()
            mock_warning.assert_called()
            assert "host" in str(mock_warning.call_args).lower()
    
    def test_validate_warns_on_dangerous_capabilities(self):
        """Test validation warns when dangerous capabilities are added."""
        config = SecureDockerConfig(
            capabilities_add=["SYS_ADMIN", "SYS_PTRACE"]
        )
        
        with patch('src.docker_security.logger.warning') as mock_warning:
            config.validate()
            mock_warning.assert_called()
            assert "Dangerous capabilities" in str(mock_warning.call_args)
    
    def test_validate_warns_on_high_file_descriptor_limit(self):
        """Test validation warns when file descriptor limit is high."""
        config = SecureDockerConfig(
            ulimits={"nofile": (100000, 100000), "nproc": (512, 512)}
        )
        
        with patch('src.docker_security.logger.warning') as mock_warning:
            config.validate()
            mock_warning.assert_called()
            assert "File descriptor limit" in str(mock_warning.call_args)
    
    def test_validate_warns_on_high_process_limit(self):
        """Test validation warns when process limit is high."""
        config = SecureDockerConfig(
            ulimits={"nofile": (1024, 1024), "nproc": (5000, 5000)}
        )
        
        with patch('src.docker_security.logger.warning') as mock_warning:
            config.validate()
            mock_warning.assert_called()
            assert "Process limit" in str(mock_warning.call_args)


class TestCustomSeccompProfile:
    """Test custom seccomp profile generation."""
    
    def test_create_custom_seccomp_profile(self, tmp_path):
        """Test custom seccomp profile creation."""
        output_path = tmp_path / "seccomp.json"
        
        create_custom_seccomp_profile(output_path)
        
        assert output_path.exists()
        
        # Parse and validate JSON
        with open(output_path) as f:
            profile = json.load(f)
        
        assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
        assert "syscalls" in profile
        assert len(profile["syscalls"]) > 0
        
        # Check allowed syscalls
        allowed_syscalls = profile["syscalls"][0]["names"]
        assert "read" in allowed_syscalls
        assert "write" in allowed_syscalls
        assert "execve" in allowed_syscalls
        
        # Ensure dangerous syscalls are NOT in allowed list
        assert "ptrace" not in allowed_syscalls
        assert "reboot" not in allowed_syscalls
        assert "mount" not in allowed_syscalls


class TestConfigFactories:
    """Test configuration factory functions."""
    
    def test_get_default_config(self):
        """Test default config factory."""
        config = get_default_config()
        
        assert isinstance(config, SecureDockerConfig)
        assert config.seccomp_profile == "default"
        assert config.network_mode == "none"
        assert config.read_only_rootfs is True
    
    def test_get_permissive_config(self):
        """Test permissive config factory (for development)."""
        with patch('src.docker_security.logger.warning') as mock_warning:
            config = get_permissive_config()
            
            assert isinstance(config, SecureDockerConfig)
            assert config.seccomp_profile == "unconfined"
            assert config.network_mode == "bridge"
            assert config.ulimits["nofile"] == (4096, 4096)
            
            # Should warn about permissive mode
            mock_warning.assert_called()
            assert "PERMISSIVE" in str(mock_warning.call_args)


class TestIntegration:
    """Integration tests with KernelLifecycle."""
    
    def test_docker_args_contain_all_security_features(self):
        """Test that generated Docker args include all Phase 3.2 features."""
        config = get_default_config()
        args = config.to_docker_args()
        
        # Must have all security features
        required_flags = [
            '--security-opt',  # Seccomp + no-new-privileges
            '--read-only',     # Read-only root
            '--network',       # Network isolation
            '--cap-drop',      # Drop capabilities
            '--cap-add',       # Add minimal capabilities
            '--ulimit',        # Resource limits
            '--memory',        # Memory limit
            '--tmpfs',         # Writable tmpfs
            '--init',          # Signal handling
        ]
        
        for flag in required_flags:
            assert flag in args, f"Missing required security flag: {flag}"
    
    def test_docker_args_order_is_consistent(self):
        """Test that Docker args are generated in consistent order."""
        config1 = get_default_config()
        config2 = get_default_config()
        
        args1 = config1.to_docker_args()
        args2 = config2.to_docker_args()
        
        # Should be identical for same config
        assert args1 == args2


class TestBackwardCompatibility:
    """Test backward compatibility with existing Docker configurations."""
    
    def test_phase_2_flags_still_present(self):
        """Test that Phase 2 security flags are preserved."""
        config = get_default_config()
        args = config.to_docker_args()
        
        # Phase 2 flags that must still be present
        assert '--network' in args
        assert 'none' in args  # Network isolation
        assert '--read-only' in args  # Read-only root
        assert '--security-opt' in args
        # Check no-new-privileges is in security-opt values
        security_indices = [i for i, x in enumerate(args) if x == '--security-opt']
        security_values = [args[i + 1] for i in security_indices if i + 1 < len(args)]
        assert 'no-new-privileges' in security_values
    
    def test_memory_limit_preserved(self):
        """Test that memory limit from Phase 2 is preserved."""
        config = get_default_config()
        
        assert config.memory_limit == "4g"
        
        args = config.to_docker_args()
        assert '--memory' in args
        memory_idx = args.index('--memory')
        assert args[memory_idx + 1] == '4g'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
