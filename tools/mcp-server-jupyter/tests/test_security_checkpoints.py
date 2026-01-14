import pytest
import os
import dill
from pathlib import Path
from src.session import SessionManager


@pytest.mark.asyncio
async def test_checkpoint_security(tmp_path):
    """Verify that tampered checkpoints are rejected."""
    nb_path = tmp_path / "security_test.ipynb"
    # Create a minimal notebook with one code cell
    from src.notebook import create_notebook
    create_notebook(str(nb_path), initial_cells=[{"type": "code", "content": "# initial"}])

    manager = SessionManager()
    
    # 1. Create a "Malicious" Checkpoint manually
    ckpt_dir = nb_path.parent / ".mcp"
    ckpt_dir.mkdir()
    ckpt_path = ckpt_dir / "malicious.pkl"
    
    payload = {"pwned": True}
    data = dill.dumps(payload)
    
    # Sign it with the WRONG key (simulating a different server instance or attacker)
    import hmac
    import hashlib
    fake_secret = b'wrong_secret_key'
    signature = hmac.new(fake_secret, data, hashlib.sha256).hexdigest()
    
    with open(ckpt_path, 'wb') as f:
        f.write(signature.encode('utf-8'))
        f.write(data)
        
    # 2. Start a real kernel (needed to run the load code)
    await manager.start_kernel(str(nb_path))
    
    # 3. Try to load it (should produce restore error)
    load_id = await manager.load_checkpoint(str(nb_path), "malicious")

    # Poll for result
    import asyncio
    status = {'status': 'running'}
    for _ in range(100):
        status = manager.get_execution_status(str(nb_path), load_id)
        if status['status'] in ('completed', 'error'):
            break
        await asyncio.sleep(0.1)
    
    # 4. Assert Security Failure
    output = status.get('output', '') or ''
    assert 'signature' in output.lower() or 'restore' in output.lower()
    
    # 5. Verify Successful Load (Happy Path)
    # Run a quick cell to set a variable
    exec_id = await manager.execute_cell_async(str(nb_path), 0, "secret_var = 42")
    # Wait for it to complete
    for _ in range(100):
        s = manager.get_execution_status(str(nb_path), exec_id)
        if s['status'] in ('completed', 'error'):
            break
        await asyncio.sleep(0.05)

    # Save a real checkpoint
    save_id = await manager.save_checkpoint(str(nb_path), "valid")

    # Wait for save completion
    for _ in range(100):
        s = manager.get_execution_status(str(nb_path), save_id)
        if s['status'] in ('completed', 'error'):
            break
        await asyncio.sleep(0.05)

    s_output = s.get('output', '') or ''
    assert 'checkpoint saved' in s_output.lower() or 'signed' in s_output.lower()

    # Load it back
    load_id2 = await manager.load_checkpoint(str(nb_path), "valid")
    for _ in range(100):
        s2 = manager.get_execution_status(str(nb_path), load_id2)
        if s2['status'] in ('completed', 'error'):
            break
        await asyncio.sleep(0.05)

    assert 'state restored' in (s2.get('output','') or '').lower()

    await manager.shutdown_all()
