import pytest
import os
import json
import subprocess
import time
import asyncio
from src.session import SessionManager

@pytest.mark.asyncio
async def test_reconcile_zombies_tmpdir(tmp_path):
    manager = SessionManager()
    # Set persistence dir to tmp path
    manager.persistence_dir = tmp_path

    # Start a subprocess that sleeps (use python to make it detectable as a python kernel-like process)
    import sys
    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    pid = p.pid

    # Create a fake session file
    import hashlib
    path_hash = hashlib.md5(str('/tmp/zombie.ipynb').encode()).hexdigest()
    session_file = tmp_path / f"session_{path_hash}.json"
    with open(session_file, 'w') as f:
        json.dump({
            'notebook_path': '/tmp/zombie.ipynb',
            'connection_file': '/tmp/fake',
            'pid': pid,
            'env_info': {},
            'created_at': 'now'
        }, f)

    # Run reconcile_zombies
    await manager.reconcile_zombies()

    # Process should be terminated
    assert p.poll() is not None, "Zombie process was not terminated"
    # The session file should be removed
    assert not session_file.exists()


def test_prlimit_injected_for_system_python(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda x: '/usr/bin/prlimit')

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

    monkeypatch.setattr('src.session.AsyncKernelManager', DummyKM)

    manager = SessionManager()
    nb_path = '/tmp/dummy_prlimit.ipynb'
    open(nb_path, 'w').write('{}')

    import asyncio
    asyncio.run(manager.start_kernel(nb_path))

    km = manager.sessions[list(manager.sessions.keys())[0]]['km']
    assert km.kernel_cmd[0] == 'prlimit'
    assert any(arg.startswith('--as=') for arg in km.kernel_cmd)
