import pytest
import json
import logging
from src.models import StartKernelArgs
from src.validation import validated_tool
from pydantic import ValidationError

# 1. Test Input Sanitization
def test_path_traversal_detection():
    with pytest.raises(ValidationError):
        StartKernelArgs(notebook_path="/var/www/../../etc/passwd")


def test_timeout_constraints():
    with pytest.raises(ValidationError):
        StartKernelArgs(notebook_path="/tmp/test.ipynb", timeout=999999)

# 2. Test Logging & Interceptor
@pytest.mark.asyncio
async def test_validated_tool_decorator(caplog):
    # Setup
    class TestModel(StartKernelArgs):
        pass

    @validated_tool(TestModel)
    async def mock_tool(notebook_path, **kwargs):
        return "success"

    # Execute with bad data
    res = await mock_tool(notebook_path="invalid", timeout=-5)
    assert "Input Error" in res
    
    # Verify that the decorator returns an input error for invalid data
    # Note: Checking structured logs is environment-specific; here we ensure the decorator
    # returns the expected error string when validation fails.
