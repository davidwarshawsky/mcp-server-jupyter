import pytest
import asyncio
from pathlib import Path
from .harness import MCPServerHarness

@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_error_handling_and_recovery(tmp_path):
    """
    Test Phase 4: Smart Error Recovery.
    Verifies that exceptions in the kernel produce:
    1. Standard traceback in the output.
    2. Hidden MCP sidecar JSON for the agent.
    """
    package_root = str(Path(__file__).parent.parent)
    harness = MCPServerHarness(cwd=package_root)
    nb_path = tmp_path / "test_error.ipynb"
    
    try:
        await harness.start()
        
        # 1. Create Notebook and Start Kernel
        await harness.send_request("create_notebook", {"notebook_path": str(nb_path)})
        await harness.read_response(timeout=10)
        await harness.send_request("start_kernel", {"notebook_path": str(nb_path)})
        await harness.read_response(timeout=30)  # Kernel startup can take a while
        
        # 2. Trigger an Exception
        code = "val = 10 / 0"
        await harness.send_request("run_cell_async", {
            "notebook_path": str(nb_path), 
            "index": 0, 
            "code_override": code
        })
        await harness.read_response(timeout=15) # Task ID
        
        # 3. Analyze Output
        found_traceback = False
        found_sidecar = False
        
        for _ in range(10):
            try:
                msg = await harness.read_response(timeout=10)
            except TimeoutError:
                break  # No more messages
            if msg.get("method") == "notebook/output":
                content = msg['params']['content']
                text = str(content)
                print(f"DEBUG MSG: {text}") # Print all output for debugging
                
                # Check for standard traceback parts
                if "ZeroDivisionError" in text:
                    found_traceback = True
                    
                    # Check for sidecar
                    if "__MCP_ERROR_CONTEXT_START__" in text:
                        found_sidecar = True
                    
            if found_traceback and found_sidecar:
                break
                
        assert found_traceback, "Standard traceback not found in output"
        assert found_sidecar, "Smart Error Recovery sidecar JSON not found in output"

    finally:
        await harness.stop()

@pytest.mark.asyncio
async def test_lifecycle_management(tmp_path):
    """
    Test Phase 2: Lifecycle Management.
    Verifies stopping a kernel cleans up resources.
    """
    package_root = str(Path(__file__).parent.parent)
    harness = MCPServerHarness(cwd=package_root)
    nb_path = tmp_path / "test_lifecycle.ipynb"
    
    try:
        await harness.start()
        
        # 1. Start Kernel
        await harness.send_request("create_notebook", {"notebook_path": str(nb_path)})
        await harness.read_response()
        await harness.send_request("start_kernel", {"notebook_path": str(nb_path)})
        start_resp = await harness.read_response()
        
        # Extract PID (approximate check)
        assert "Kernel started" in start_resp['result']['content'][0]['text']
        
        # 2. Stop Kernel
        await harness.send_request("stop_kernel", {"notebook_path": str(nb_path)})
        resp = await harness.read_response()
        
        # Depending on implementation, stop_kernel might return something or just empty
        # Checking if it didn't error is a good start. 
        # Ideally we'd check if the process is gone, but that requires OS access matching the PID.
        assert "result" in resp
        
        # 3. Verify Restart (should be possible)
        await harness.send_request("start_kernel", {"notebook_path": str(nb_path)})
        resp = await harness.read_response()
        assert "Kernel started" in resp['result']['content'][0]['text']

    finally:
        await harness.stop()
