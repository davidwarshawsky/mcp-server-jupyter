"""
Environment Tools - dependency analysis and environment helpers.

Provides: analyze_dependencies(notebook_dir) to scan .ipynb files and recommend
clean requirements.txt updates.
"""

import ast
import json
import sys
from pathlib import Path

import nbformat


def _get_imports_from_file(path: str) -> set:
    """Extract top-level imports from a Python file/notebook."""
    code = ""
    if path.endswith(".ipynb"):
        try:
            nb = nbformat.read(path, as_version=4)
            for cell in nb.cells:
                if cell.cell_type == "code":
                    # cell.source may be either list or str
                    src = (
                        cell.source
                        if isinstance(cell.source, str)
                        else "\n".join(cell.source)
                    )
                    code += src + "\n"
        except Exception:
            return set()
    else:
        return set()

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return imports


def register_environment_tools(mcp, session_manager):
    """Register environment related tools with MCP."""

    @mcp.tool()
    def analyze_dependencies(notebook_dir: str = ".") -> str:
        """
        Scan notebooks and recommend requirements.txt updates.

        Returns: JSON report of used imports, missing packages, and potentially unused requirements.
        """
        root = Path(notebook_dir)
        used_imports = set()
        for nb in root.glob("**/*.ipynb"):
            if ".ipynb_checkpoints" in str(nb):
                continue
            used_imports.update(_get_imports_from_file(str(nb)))

        # Filter stdlib (approximate using builtin module names)
        stdlib = set(sys.builtin_module_names)
        cleaned_imports = {i for i in used_imports if i and i not in stdlib}

        # Read requirements.txt
        req_file = root / "requirements.txt"
        listed_reqs = set()
        if req_file.exists():
            for line in req_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                clean = line.split("==")[0].split(">=")[0].split("<=")[0].strip()
                if clean:
                    listed_reqs.add(clean.lower())

        missing = sorted([i for i in cleaned_imports if i.lower() not in listed_reqs])
        potentially_unused = sorted(
            [r for r in listed_reqs if r not in {i.lower() for i in cleaned_imports}]
        )

        report = {
            "status": "complete",
            "used_imports": sorted(cleaned_imports),
            "missing_from_requirements": missing,
            "potentially_unused": potentially_unused,
            "recommendation": "Review 'potentially_unused' and remove them. Add 'missing' packages if needed.",
        }

        return json.dumps(report, indent=2)


"""
Environment Tools - Environment detection and management tools.

Includes: find_python_executables, validate_python_executable,
auto_detect_environment, create_venv
"""

import json
import sys
from typing import Optional
from mcp_server_jupyter import environment
from mcp_server_jupyter.observability import get_logger

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
