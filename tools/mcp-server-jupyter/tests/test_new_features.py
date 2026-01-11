import pytest
import json
from src import validation, utils, environment
from src.utils import ToolResult

def test_check_code_syntax_valid():
    code = "print('hello')"
    valid, error = validation.check_code_syntax(code)
    assert valid is True
    assert error is None

def test_check_code_syntax_invalid():
    code = "print('hello'"
    valid, error = validation.check_code_syntax(code)
    assert valid is False
    assert "SyntaxError" in error

def test_tool_result_serialization():
    res = ToolResult(success=True, data={"foo": "bar"}, user_suggestion="Retry")
    json_str = res.to_json()
    data = json.loads(json_str)
    assert data['success'] is True
    assert data['data']['foo'] == "bar"
    assert data['user_suggestion'] == "Retry"
    assert data['error_msg'] is None

def test_tool_result_error():
    res = ToolResult(success=False, data=None, error_msg="Failed")
    data = json.loads(res.to_json())
    assert data['success'] is False
    assert data['error_msg'] == "Failed"

from unittest.mock import patch

def test_install_package_mock():
    # Mock subprocess.run
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Successfully installed"
        
        success, output = environment.install_package("pandas")
        assert success is True
        assert "Successfully installed" in output
        mock_run.assert_called_once()
