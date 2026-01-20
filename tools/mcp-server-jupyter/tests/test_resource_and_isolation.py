import pytest
import os
from src import utils
from src.models import StartKernelArgs
from unittest.mock import patch, MagicMock

@pytest.mark.parametrize('env_val,expected', [
    ('5', 5),
    ('10', 10),
])
def test_io_pool_configurable(monkeypatch, env_val, expected):
    monkeypatch.setenv('MCP_IO_POOL_SIZE', env_val)
    # re-import module to pick up env var
    import importlib
    importlib.reload(utils)
    assert getattr(utils, 'io_pool', None) is not None
    max_workers = getattr(utils.io_pool, '_max_workers', None)
    assert max_workers == expected


def test_prlimit_prefix_applied(monkeypatch):
    # Ensure when prlimit exists, kernel_cmd is prefixed
    monkeypatch.setattr('shutil.which', lambda x: '/usr/bin/prlimit')

    # Replace AsyncKernelManager with a dummy to inspect kernel_cmd
    class DummyKM:
        def __init__(self):
            self.kernel_cmd = None
        async def start_kernel(self, cwd=None, env=None):
            self.has_kernel = True

        def client(self):
            kc = MagicMock()
            kc.start_channels = MagicMock()
            async def wait_for_ready(timeout=1):
                return True
            kc.wait_for_ready = wait_for_ready
            return kc

    monkeypatch.setattr('src.session.AsyncKernelManager', DummyKM)

    from src.session import SessionManager
    manager = SessionManager()

    # Use a temp notebook file path
    nb_path = '/tmp/dummy_notebook.ipynb'
    # create minimal notebook
    open(nb_path, 'w').write('{}')

    # Start kernel (should set km.kernel_cmd)
    import asyncio
    try:
        asyncio.run(manager.start_kernel(nb_path, venv_path=None))

        km = manager.sessions[list(manager.sessions.keys())[0]]['km']
        assert km.kernel_cmd is not None
        # prlimit prefix applied
        assert km.kernel_cmd[0] == 'prlimit'
        assert '--as=4294967296' in km.kernel_cmd
    finally:
        # Cleanup
        manager.sessions.clear()


def test_agent_cwd_isolation(monkeypatch, tmp_path):
    # Dummy kernel manager to avoid actually launching kernels
    class DummyKM:
        def __init__(self):
            self.kernel_cmd = None
        async def start_kernel(self, cwd=None, env=None):
            self.has_kernel = True
        def client(self):
            kc = MagicMock()
            kc.start_channels = MagicMock()
            async def wait_for_ready(timeout=1):
                return True
            kc.wait_for_ready = wait_for_ready
            return kc

    monkeypatch.setattr('src.session.AsyncKernelManager', DummyKM)

    from src.session import SessionManager
    manager = SessionManager()

    # create notebook in base dir
    nb = tmp_path / 'agent_test' / 'notebook.ipynb'
    nb.parent.mkdir(parents=True)
    nb.write_text('{}')

    import asyncio
    try:
        # Start kernel with agent id
        asyncio.run(manager.start_kernel(str(nb), agent_id='alice'))
        sess = manager.sessions.get(str(nb.resolve()))
        assert sess is not None
        # CWD should contain agent_alice (could be agent_test/agent_alice)
        assert 'agent_alice' in sess['cwd'], f"Expected 'agent_alice' in cwd, got: {sess['cwd']}"
    finally:
        # Cleanup
        manager.sessions.clear()
