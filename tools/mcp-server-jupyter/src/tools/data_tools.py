"""
Data Tools - SQL queries on DataFrames and package management.

Includes: query_dataframes, install_package
"""

import time
from src.utils import ToolResult
from src.validation import validated_tool
from src.models import QueryDataframesArgs, InstallPackageArgs
from src.observability import get_logger

logger = get_logger(__name__)


def register_data_tools(mcp, session_manager):
    """Register data-related tools with the MCP server."""
    from src.utils import offload_to_thread

    @mcp.tool()
    @offload_to_thread
    @validated_tool(QueryDataframesArgs)
    async def query_dataframes(notebook_path: str, sql_query: str):
        """
        [SUPERPOWER] Run SQL directly on active DataFrames using DuckDB.

        Execute SQL queries against pandas/polars DataFrames in memory.
        No data copying required - DuckDB reads directly from Python objects.

        Args:
            notebook_path: Path to notebook with running kernel
            sql_query: SQL query (e.g., "SELECT * FROM df WHERE amount > 100")

        Returns:
            JSON with query results as markdown table

        Example:
            query_dataframes("analysis.ipynb", "SELECT region, SUM(revenue) FROM df_sales GROUP BY region")
            # Returns: Markdown table with aggregated results

        Wow Factor:
            Users can explore data with SQL instead of pandas syntax.
            "Show me top 5 users by revenue" becomes a simple SQL query.
        """
        from src.data_tools import query_dataframes as _query_df

        return await _query_df(session_manager, notebook_path, sql_query)

    @mcp.tool()
    @validated_tool(InstallPackageArgs)
    async def install_package(notebook_path: str, package: str):
        """
        [ENVIRONMENT] Install a Python package in the kernel's environment.

        Better than !pip install because:
        - Uses the correct pip for the kernel
        - Returns clear success/failure
        - Reminds about kernel restart if needed

        Args:
            notebook_path: Path to notebook (determines which kernel environment)
            package: Package name or pip specifier (e.g., "pandas", "numpy>=1.20")

        Returns:
            JSON with installation status and instructions

        Example:
            install_package("analysis.ipynb", "pandas==2.0.0")
            # Returns: {"success": true, "message": "Package installed. Restart kernel to use."}
        """
        session = session_manager.get_session(notebook_path)
        if not session:
            return ToolResult(
                success=False,
                data={},
                error_msg="No running kernel. Call start_kernel first.",
            ).to_json()

        # [DUH FIX: PIP INSTALL BLIND SPOT] Check if package is already installed
        # Extract package name (handle "pandas==2.0.0" -> "pandas")
        pkg_name = package.split("==")[0].split(">=")[0].split("<")[0].split("[")[0].strip()
        
        check_code = f"""
import importlib.util
import sys

# Check if package is already installed
try:
    spec = importlib.util.find_spec("{pkg_name}")
    if spec is not None:
        print("ALREADY_INSTALLED")
        sys.exit(0)
except (ImportError, ValueError, ModuleNotFoundError):
    pass
print("NOT_FOUND")
"""

        # Execute check using SessionManager's queue
        try:
            check_exec_id = await session_manager.execute_cell_async(
                notebook_path, -1, check_code
            )
        except RuntimeError:
            # If queue is full, proceed to install (best effort)
            check_exec_id = None

        # Check result
        if check_exec_id:
            timeout = 10
            start_time = time.time()
            while time.time() - start_time < timeout:
                status = session_manager.get_execution_status(notebook_path, check_exec_id)
                if status.get("status") == "completed":
                    output = status.get("output", "").strip()
                    if "ALREADY_INSTALLED" in output:
                        return ToolResult(
                            success=True,
                            data={"package": pkg_name, "status": "already_installed"},
                            error_msg=None,
                        ).to_json()
                    break
            await asyncio.sleep(0.1)

        # Install command using sys.executable (correct Python for kernel)
        install_code = f"""
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "{package}"],
    capture_output=True,
    text=True
)

print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("RETURNCODE:", result.returncode)
"""

        # Execute installation using SessionManager's queue (index -1 = internal tool)
        try:
            exec_id = await session_manager.execute_cell_async(
                notebook_path, -1, install_code
            )
        except RuntimeError as e:
            # Queue is full
            return ToolResult(
                success=False,
                data={},
                error_msg=f"Execution queue is full. Cannot install package. {str(e)}",
            ).to_json()

        if not exec_id:
            return ToolResult(
                success=False, data={}, error_msg="Failed to submit installation"
            ).to_json()

        # Wait for completion
        timeout = 60  # Package installation can take time
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = session_manager.get_execution_status(notebook_path, exec_id)
            if status.get("status") == "completed":
                output = status.get("output", "")

                # Parse output for return code
                if "RETURNCODE: 0" in output:
                    # [DUH FIX #1] Auto-update requirements.txt for portability
                    _update_requirements_txt(notebook_path, package)

                    # [HIDDEN DEPENDENCY TRAP] Check for requirements.txt to prompt user
                    from pathlib import Path
                    from src.utils import get_project_root

                    project_root = get_project_root(Path(notebook_path).parent)
                    req_path = project_root / "requirements.txt"
                    requirements_found = req_path.exists()

                    return ToolResult(
                        success=True,
                        data={
                            "package": package,
                            "output": output,
                            "requires_restart": True,
                            "requirements_path": (
                                str(req_path) if requirements_found else None
                            ),
                        },
                        # [UX] Stronger warning about Restart "Wipeout"
                        user_message=f"✅ Package '{package}' installed successfully. Added to requirements.txt.\n\n⚠️ **RESTART REQUIRED**: Restarting kernel will **CLEAR ALL MEMORY** (variables, loaded data). Save intermediate results/checkpoints first if needed.",
                    ).to_json()
                else:
                    return ToolResult(
                        success=False,
                        data={"package": package, "output": output},
                        error_msg="Installation failed. Check output for details.",
                    ).to_json()

            elif status.get("status") == "error":
                return ToolResult(
                    success=False,
                    data={"package": package},
                    error_msg=status.get("error", "Unknown installation error"),
                ).to_json()

            await asyncio.sleep(0.5)

        return ToolResult(
            success=False,
            data={"package": package, "exec_id": exec_id},
            error_msg=f"Installation timed out after {timeout}s. Check status with get_execution_status.",
        ).to_json()


def _update_requirements_txt(notebook_path: str, package: str) -> None:
    """
    Append package to requirements.txt in the workspace root.

    This ensures notebooks are portable - colleagues can run:
        pip install -r requirements.txt

    Args:
        notebook_path: Path to notebook (used to find workspace root)
        package: Package specifier (e.g., "pandas>=2.0", "numpy")
    """
    from pathlib import Path

    # Normalize package name (strip version for deduplication check)
    pkg_name = (
        package.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
    )

    # Find workspace root (directory containing notebook, or parent with .git)
    nb_path = Path(notebook_path).resolve()
    workspace_root = nb_path.parent

    # Look for .git to find true workspace root
    for parent in [nb_path.parent] + list(nb_path.parents):
        if (parent / ".git").exists():
            workspace_root = parent
            break

    req_file = workspace_root / "requirements.txt"

    # Read existing requirements
    existing_packages = set()
    if req_file.exists():
        with open(req_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    # Extract package name (before version specifier)
                    existing_pkg = (
                        line.split("==")[0]
                        .split(">=")[0]
                        .split("<=")[0]
                        .split("[")[0]
                        .strip()
                    )
                    existing_packages.add(existing_pkg.lower())

    # Only add if not already present
    if pkg_name.lower() not in existing_packages:
        with open(req_file, "a", encoding="utf-8") as f:
            if not req_file.exists() or req_file.stat().st_size == 0:
                f.write("# Auto-generated by MCP Jupyter\n")
            f.write(f"{package}\n")


# Import asyncio at module level for the sleep call
import asyncio
