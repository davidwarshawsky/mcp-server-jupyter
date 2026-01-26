import pytest
import os
import json
import subprocess
import asyncio
from src.session import SessionManager


@pytest.mark.asyncio
async def test_reconcile_zombies_tmpdir(tmp_path):
    import uuid as uuid_mod

    manager = SessionManager()
    # Set persistence dir to tmp path
    manager.persistence_dir = tmp_path
    manager.state_manager.persistence_dir = tmp_path

    # Create a UUID for the fake kernel
    kernel_uuid = str(uuid_mod.uuid4())

    # Start a subprocess that sleeps with the MCP_KERNEL_ID environment variable
    import sys

    env = os.environ.copy()
    env["MCP_KERNEL_ID"] = kernel_uuid
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], env=env)
    pid = p.pid

    # Create a fake session file with kernel_uuid and a dead server_pid
    import hashlib

    path_hash = hashlib.md5(str("/tmp/zombie.ipynb").encode()).hexdigest()
    session_file = tmp_path / f"session_{path_hash}.json"
    with open(session_file, "w") as f:
        json.dump(
            {
                "notebook_path": "/tmp/zombie.ipynb",
                "connection_file": "/tmp/fake",
                "pid": pid,
                "kernel_uuid": kernel_uuid,
                "server_pid": 99999999,  # Non-existent server PID (simulates dead server)
                "env_info": {},
                "created_at": "now",
            },
            f,
        )

    # Run reconcile_zombies
    await manager.reconcile_zombies()

    # Wait a moment for process to be terminated
    await asyncio.sleep(0.5)

    # Process should be terminated
    assert p.poll() is not None, "Zombie process was not terminated"
    # The session file should be removed
    assert not session_file.exists()


def test_prlimit_injected_for_system_python(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/prlimit")

    class DummyKM:
        def __init__(self):
            self.kernel_cmd = None
            self.has_kernel = False

        async def start_kernel(self, cwd=None, env=None):
            self.has_kernel = True

        def client(self):
            class KClient:
                def start_channels(self):
                    pass

                async def wait_for_ready(self, timeout=1):
                    return True

            return KClient()

    monkeypatch.setattr("src.session.AsyncKernelManager", DummyKM)

    manager = SessionManager()
    nb_path = "/tmp/dummy_prlimit.ipynb"
    open(nb_path, "w").write("{}")

    import asyncio

    asyncio.run(manager.start_kernel(nb_path))

    km = manager.sessions[list(manager.sessions.keys())[0]]["km"]
    assert km.kernel_cmd[0] == "prlimit"
    assert any(arg.startswith("--as=") for arg in km.kernel_cmd)


def test_reaper_docker_cleanup(tmp_path, monkeypatch):
    """
    Test that the reaper correctly invokes 'docker rm -f' for zombie containers.
    """
    from unittest.mock import Mock
    from src.session import SessionManager

    # Mock subprocess.run
    mock_run = Mock()
    monkeypatch.setattr(subprocess, "run", mock_run)

    manager = SessionManager()
    manager.persistence_dir = tmp_path
    manager.state_manager.persistence_dir = tmp_path

    # Create fake session file with container_name
    # Use a unique name to avoid conflicts
    session_file = tmp_path / "session_docker_zombie.json"
    with open(session_file, "w") as f:
        json.dump(
            {
                "notebook_path": "/tmp/docker_zombie.ipynb",
                "connection_file": "/tmp/fake",
                "pid": 12345,
                "server_pid": 99999999,  # Dead server
                "env_info": {"container_name": "mcp-kernel-test-uuid"},
                "created_at": "now",
            },
            f,
        )

    # Run reaper logic directly
    manager.state_manager.reconcile_zombies()

    # Assert docker rm was called with timeout
    mock_run.assert_called_with(
        ["docker", "rm", "-f", "mcp-kernel-test-uuid"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )

    # Session file should be cleaned up
    assert not session_file.exists()
