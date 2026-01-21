"""
Data Tools - SQL queries on DataFrames and package management.

Includes: query_dataframes, install_package
"""

import json
import time
from src.utils import ToolResult
from src.validation import validated_tool
from src.models import QueryDataframesArgs, InstallPackageArgs
from src.observability import get_logger

logger = get_logger(__name__)


def register_data_tools(mcp, session_manager):
    """Register data-related tools with the MCP server."""
    
    @mcp.tool()
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
                error_msg="No running kernel. Call start_kernel first."
            ).to_json()
        
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
            exec_id = await session_manager.execute_cell_async(notebook_path, -1, install_code)
        except RuntimeError as e:
            # Queue is full
            return ToolResult(
                success=False,
                data={},
                error_msg=f"Execution queue is full. Cannot install package. {str(e)}"
            ).to_json()
        
        if not exec_id:
            return ToolResult(
                success=False,
                data={},
                error_msg="Failed to submit installation"
            ).to_json()
        
        # Wait for completion
        timeout = 60  # Package installation can take time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = session_manager.get_execution_status(notebook_path, exec_id)
            if status.get('status') == 'completed':
                output = status.get('output', '')
                
                # Parse output for return code
                if 'RETURNCODE: 0' in output:
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
                            "requirements_path": str(req_path) if requirements_found else None
                        },
                        # [UX] Stronger warning about Restart "Wipeout"
                        user_message=f"✅ Package '{package}' installed successfully.\n\n⚠️ **RESTART REQUIRED**: Restarting kernel will **CLEAR ALL MEMORY** (variables, loaded data). Save intermediate results/checkpoints first if needed."
                    ).to_json()
                else:
                    return ToolResult(
                        success=False,
                        data={"package": package, "output": output},
                        error_msg=f"Installation failed. Check output for details."
                    ).to_json()
            
            elif status.get('status') == 'error':
                return ToolResult(
                    success=False,
                    data={"package": package},
                    error_msg=status.get('error', 'Unknown installation error')
                ).to_json()
            
            await asyncio.sleep(0.5)
        
        return ToolResult(
            success=False,
            data={"package": package, "exec_id": exec_id},
            error_msg=f"Installation timed out after {timeout}s. Check status with get_execution_status."
        ).to_json()


# Import asyncio at module level for the sleep call
import asyncio
