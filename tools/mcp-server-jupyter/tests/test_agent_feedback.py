import pytest
import shutil
import json
from pathlib import Path
from .harness import MCPServerHarness

@pytest.mark.asyncio
async def test_notify_edit_result(tmp_path):
    """
    Test the 'notify_edit_result' tool which closes the agent feedback loop.
    """
    package_root = str(Path(__file__).parent.parent)
    harness = MCPServerHarness(cwd=package_root)
    nb_path = tmp_path / "test_feedback.ipynb"
    
    try:
        await harness.start()
        
        # 1. Start Server & Kernel
        await harness.send_request("create_notebook", {"notebook_path": str(nb_path)})
        await harness.read_response()
        
        # 2. Call the tool
        # In a real flow, Agent proposes -> Client applies -> Client notifies.
        # Here we just test the notification tool response.
        
        proposal_id = "prop-123"
        await harness.send_request("notify_edit_result", {
            "notebook_path": str(nb_path),
            "proposal_id": proposal_id,
            "status": "accepted",
            "message": "Looks good."
        })
        
        response = await harness.read_response()
        
        assert "result" in response
        result_content = response['result']['content'][0]['text']
        result_json = json.loads(result_content)
        
        assert result_json['status'] == 'ack'
        assert 'timestamp' in result_json

    finally:
        await harness.stop()
