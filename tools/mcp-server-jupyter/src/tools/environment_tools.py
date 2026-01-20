"""
Environment Tools - Environment detection and management tools.

Includes: find_python_executables, validate_python_executable,
auto_detect_environment, create_venv
"""

import json
import sys
from typing import Optional
from src import environment
from src.observability import get_logger

logger = get_logger(__name__)


def register_environment_tools(mcp, session_manager):
    """Register environment management tools with the MCP server."""
    
    @mcp.tool()
    def find_python_executables():
        """
        Discovers all Python interpreters on the system.
        Scans PATH and common installation locations.
        Returns JSON list of discovered interpreters with version and type info.
        """
        executables = environment.find_python_executables()
        return json.dumps(executables, indent=2)

    @mcp.tool()
    def validate_python_executable(python_path: str):
        """
        Validates a Python executable.
        Returns detailed validation results including version and pip availability.
        """
        result = environment.validate_python_executable(python_path)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def auto_detect_environment(notebook_path: Optional[str] = None):
        """
        Automatically detects the best Python environment to use.
        If notebook_path is provided, looks for .venv or environment in notebook directory.
        Returns JSON with python_path, env_type, env_name, and version.
        """
        result = environment.auto_detect_environment(notebook_path)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def create_venv(path: str, python_executable: str = ""):
        """
        Creates a new virtual environment.
        path: Path where the venv will be created
        python_executable: Optional Python executable to use (defaults to sys.executable)
        """
        if python_executable:
            result = environment.create_venv(path, python_executable)
        else:
            result = environment.create_venv(path, sys.executable)
        return json.dumps(result, indent=2)
