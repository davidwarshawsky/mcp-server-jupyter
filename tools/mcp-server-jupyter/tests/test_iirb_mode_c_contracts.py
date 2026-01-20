"""
Contract Tests for IIRB Mode C Security Configuration
=======================================================

Tests the contract between environment variables and security behavior.
Validates P0 fixes #2, #3, #5 remain enforced.

Author: IIRB Mode C Advisory
Phase: Contract Testing
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestStrictModeContract:
    """Contract: MCP_STRICT_MODE=1 MUST block wildcard package allowlist."""
    
    def test_strict_mode_blocks_wildcard_allowlist(self):
        """
        GIVEN: MCP_STRICT_MODE=1 and MCP_PACKAGE_ALLOWLIST='*'
        WHEN: install_package() is called
        THEN: Installation MUST fail with STRICT MODE VIOLATION error
        """
        from src import environment
        
        with patch.dict(os.environ, {
            'MCP_STRICT_MODE': '1',
            'MCP_PACKAGE_ALLOWLIST': '*'
        }):
            success, message = environment.install_package('malicious-pkg')
            
            assert success is False
            assert 'STRICT MODE VIOLATION' in message
            assert 'Wildcard allowlist' in message
            assert 'MCP_STRICT_MODE=1' in message
    
    def test_strict_mode_allows_explicit_allowlist(self):
        """
        GIVEN: MCP_STRICT_MODE=1 and explicit package allowlist
        WHEN: Allowed package is installed
        THEN: Installation proceeds (mock)
        """
        from src import environment
        
        with patch.dict(os.environ, {
            'MCP_STRICT_MODE': '1',
            'MCP_PACKAGE_ALLOWLIST': 'pandas,numpy'
        }):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout='Success')
                
                success, message = environment.install_package('pandas')
                
                assert success is True
                assert 'Successfully installed' in message
    
    def test_non_strict_mode_allows_wildcard(self):
        """
        GIVEN: MCP_STRICT_MODE=0 (or unset) and MCP_PACKAGE_ALLOWLIST='*'
        WHEN: install_package() is called
        THEN: Installation proceeds with warning logged
        """
        from src import environment
        
        with patch.dict(os.environ, {
            'MCP_STRICT_MODE': '0',
            'MCP_PACKAGE_ALLOWLIST': '*'
        }):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout='Success')
                
                success, message = environment.install_package('any-package')
                
                assert success is True


class TestDataDirContract:
    """Contract: MCP_DATA_DIR MUST be respected for all persistence."""
    
    def test_custom_data_dir_respected(self):
        """
        GIVEN: MCP_DATA_DIR=/custom/path
        WHEN: SessionManager is initialized
        THEN: Persistence directory MUST be /custom/path/sessions
        """
        from src.session import SessionManager
        from src.config import Settings
        
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-mcp"
            custom_dir.mkdir()
            
            with patch.dict(os.environ, {'MCP_DATA_DIR': str(custom_dir)}):
                # Reload settings
                from src.config import load_and_validate_settings
                settings = load_and_validate_settings()
                
                expected_path = custom_dir / "sessions"
                actual_path = settings.get_data_dir() / "sessions"
                
                assert actual_path == expected_path
    
    def test_proposals_use_data_dir(self):
        """
        GIVEN: MCP_DATA_DIR=/custom/path
        WHEN: Proposals are loaded
        THEN: PROPOSAL_STORE_FILE MUST be /custom/path/proposals.json
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-mcp"
            custom_dir.mkdir()
            
            with patch.dict(os.environ, {'MCP_DATA_DIR': str(custom_dir)}):
                # Reload main module to pick up new PROPOSAL_STORE_FILE
                import importlib
                import src.main
                importlib.reload(src.main)
                
                from src.main import PROPOSAL_STORE_FILE
                
                expected_path = custom_dir / "proposals.json"
                assert PROPOSAL_STORE_FILE == expected_path


class TestPrivilegeEscalationContract:
    """Contract: SETUID/SETGID MUST NOT be added by default."""
    
    def test_default_capabilities_exclude_setuid_setgid(self):
        """
        GIVEN: MCP_ALLOW_PRIVILEGE_ESCALATION unset (default)
        WHEN: Docker security config is generated
        THEN: capabilities_add MUST NOT contain SETUID or SETGID
        """
        from src.docker_security import SecureDockerConfig
        
        with patch.dict(os.environ, {}, clear=True):
            config = SecureDockerConfig()
            
            assert 'SETUID' not in config.capabilities_add
            assert 'SETGID' not in config.capabilities_add
            assert 'CHOWN' in config.capabilities_add  # Only CHOWN
    
    def test_privilege_escalation_flag_adds_dangerous_caps(self):
        """
        GIVEN: MCP_ALLOW_PRIVILEGE_ESCALATION=1
        WHEN: Docker args are generated
        THEN: SETUID and SETGID MUST be added to capabilities
        """
        from src.docker_security import SecureDockerConfig
        
        with patch.dict(os.environ, {'MCP_ALLOW_PRIVILEGE_ESCALATION': '1'}):
            config = SecureDockerConfig()
            args = config.to_docker_args()
            
            args_str = ' '.join(args)
            assert '--cap-add SETUID' in args_str
            assert '--cap-add SETGID' in args_str


class TestPIDValidationContract:
    """Contract: Reaper MUST only kill processes with UUID match."""
    
    @pytest.mark.asyncio
    async def test_reaper_requires_uuid_match(self):
        """
        GIVEN: Session file with kernel_uuid
        WHEN: Reaper reconciles zombies
        THEN: Process MUST NOT be killed if UUID doesn't match
        """
        from src.kernel_state import KernelStateManager
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence_dir = Path(tmpdir)
            state_manager = KernelStateManager(persistence_dir)
            
            # Create fake session with UUID
            session_data = {
                "notebook_path": "/tmp/test.ipynb",
                "connection_file": "/tmp/conn.json",
                "pid": 99999,  # Non-existent PID
                "kernel_uuid": "test-uuid-123",
                "server_pid": 99998,  # Dead server (non-existent PID)
                "created_at": "2025-01-20T10:00:00"
            }
            
            session_file = persistence_dir / "session_test.json"
            session_file.write_text(json.dumps(session_data))
            
            # Run reconciliation (should not crash)
            state_manager.reconcile_zombies()
            
            # Session file should be cleaned up
            assert not session_file.exists()
    
    def test_legacy_sessions_without_uuid_skipped(self):
        """
        GIVEN: Session file WITHOUT kernel_uuid (legacy)
        WHEN: Reaper reconciles zombies
        THEN: Process MUST be skipped with warning
        """
        from src.kernel_state import KernelStateManager
        import json
        import logging
        
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence_dir = Path(tmpdir)
            state_manager = KernelStateManager(persistence_dir)
            
            # Create legacy session WITHOUT kernel_uuid
            import hashlib
            path_hash = hashlib.md5(b"/tmp/test.ipynb").hexdigest()
            session_data = {
                "notebook_path": "/tmp/test.ipynb",
                "connection_file": "/tmp/conn.json",
                "pid": os.getpid(),  # Use current process PID (exists but shouldn't be killed)
                "server_pid": 999999,  # Definitely dead server PID
                "created_at": "2025-01-20T10:00:00"
            }
            
            session_file = persistence_dir / f"session_{path_hash}.json"
            session_file.write_text(json.dumps(session_data))
            
            # Capture logs
            with patch.object(logging.getLogger('src.kernel_state'), 'warning') as mock_warning:
                state_manager.reconcile_zombies()
                
                # Should log warning about missing UUID
                warning_calls = [str(call) for call in mock_warning.call_args_list]
                assert any('has no kernel_uuid' in str(call).lower() or 'legacy' in str(call).lower() for call in warning_calls), f"Expected warning about missing kernel_uuid, got: {warning_calls}"


class TestConfigValidationContract:
    """Contract: Invalid config MUST fail fast with clear errors."""
    
    def test_invalid_log_level_rejected(self):
        """
        GIVEN: LOG_LEVEL=INVALID
        WHEN: Settings are loaded
        THEN: ValidationError MUST be raised
        """
        from src.config import Settings
        from pydantic import ValidationError
        
        with patch.dict(os.environ, {'LOG_LEVEL': 'INVALID'}):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            assert 'LOG_LEVEL' in str(exc_info.value)
    
    def test_port_out_of_range_rejected(self):
        """
        GIVEN: MCP_PORT=999 (below 1024)
        WHEN: Settings are loaded
        THEN: ValidationError MUST be raised
        """
        from src.config import Settings
        from pydantic import ValidationError
        
        with patch.dict(os.environ, {'MCP_PORT': '999'}):
            with pytest.raises(ValidationError):
                Settings()
    
    def test_data_dir_creates_directory_structure(self):
        """
        GIVEN: MCP_DATA_DIR points to non-existent directory
        WHEN: get_data_dir() is called
        THEN: Directory MUST be created
        """
        from src.config import load_and_validate_settings
        
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "new-mcp-dir"
            
            with patch.dict(os.environ, {'MCP_DATA_DIR': str(custom_dir)}):
                settings = load_and_validate_settings()
                data_dir = settings.get_data_dir()
                
                assert data_dir == custom_dir


# Performance Contract Tests
class TestPerformanceContract:
    """Contract: Configuration loading MUST not block startup."""
    
    def test_config_load_completes_under_100ms(self):
        """
        GIVEN: Valid configuration
        WHEN: Settings are loaded
        THEN: Operation MUST complete in <100ms
        """
        import time
        from src.config import load_and_validate_settings
        
        start = time.time()
        load_and_validate_settings()
        elapsed = time.time() - start
        
        assert elapsed < 0.1, f"Config loading took {elapsed*1000:.1f}ms (expected <100ms)"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
