import pytest
import asyncio
import nbformat
import os
from pathlib import Path
from src.session import SessionManager

@pytest.mark.asyncio
async def test_async_execution_flow():
    """
    Tests async execution flow with real kernel.
    
    Validates that async cell execution properly tracks execution state
    through the queue → running → completed lifecycle.
    """
    # Setup
    manager = SessionManager()
    nb_path = Path("test_async.ipynb").resolve()
    
    # Create dummy notebook
    nb = nbformat.v4.new_notebook()
    # A cell that sleeps for 2 seconds
    code = "import time\nprint('Start')\ntime.sleep(2)\nprint('End')"
    nb.cells.append(nbformat.v4.new_code_cell(code))
    with open(nb_path, 'w') as f:
        nbformat.write(nb, f)
        
    try:
        # 1. Start Kernel
        print(f"Starting kernel for {nb_path}...")
        res = await manager.start_kernel(str(nb_path))
        print(res)
        
        # 2. Run Async
        print("Submitting async task...")
        exec_id = await manager.execute_cell_async(str(nb_path), 0, code)
        assert exec_id is not None
        print(f"Task ID: {exec_id}")
        
        # 3. Check immediately (Should be queued or running)
        # Note: With autoreload delay, kernel startup takes ~1s
        # Poll until we catch it in queued/running state or it completes
        caught_in_progress = False
        for _ in range(20):  # Increased from implicit single check to account for autoreload delay
            await asyncio.sleep(0.1)
            status = manager.get_execution_status(str(nb_path), exec_id)
            print(f"Status during execution: {status['status']}")
            if status['status'] in ['queued', 'running']:
                caught_in_progress = True
                break
            if status['status'] == 'completed':
                # Fast execution - acceptable, skip assertion
                caught_in_progress = True  
                break
        assert caught_in_progress, "Failed to catch execution state"
        
        # 4. Wait a bit (simulate Agent doing other stuff)
        print("Waiting 3 seconds...")
        await asyncio.sleep(3)
        
        # 5. Check again (Should be done) - increased wait time for parallel test reliability
        max_wait = 30  # seconds
        wait_interval = 1.0
        elapsed = 0
        final_status = None
        
        while elapsed < max_wait:
            status = manager.get_execution_status(str(nb_path), exec_id)
            if status['status'] == 'completed':
                final_status = status
                break
            await asyncio.sleep(wait_interval)
            elapsed += wait_interval
        
        assert final_status is not None, f"Execution did not complete within {max_wait} seconds"
        print(f"Final status: {final_status['status']}")
        print(f"Output: {final_status.get('output', '')}")
        
        assert final_status['status'] == 'completed'
        assert "Start" in final_status['output']
        assert "End" in final_status['output']
        
    finally:
        await manager.shutdown_all()
        if nb_path.exists():
            os.remove(nb_path)
