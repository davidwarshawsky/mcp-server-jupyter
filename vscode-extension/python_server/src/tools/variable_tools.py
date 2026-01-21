"""
Variable Tools - Variable inspection tools.

Includes: get_variable_info, list_variables, get_variable_manifest, inspect_variable
"""

import json
from src.observability import get_logger
from src.validation import validated_tool
from src.models import (
    GetVariableInfoArgs, ListVariablesArgs, 
    GetVariableManifestArgs, InspectVariableArgs
)

logger = get_logger(__name__)


def register_variable_tools(mcp, session_manager):
    """Register variable inspection tools with the MCP server."""
    
    @mcp.tool()
    @validated_tool(GetVariableInfoArgs)
    async def get_variable_info(notebook_path: str, var_name: str):
        """
        Inspect a specific variable in the kernel without dumping all globals.
        Agent Use Case: Check 'df.columns' or 'df.shape' without loading the entire DataFrame.
        Returns: JSON with type, shape, columns, memory usage, preview, etc.
        """
        return await session_manager.get_variable_info(notebook_path, var_name)

    @mcp.tool()
    @validated_tool(ListVariablesArgs)
    async def list_variables(notebook_path: str):
        """
        List all variables in the kernel (names and types only, no values).
        Agent Use Case: Discover what variables exist before using get_variable_info.
        """
        code = """
import json
import sys
result = []
for name in dir():
    if not name.startswith('_'):
        obj = globals()[name]
        if not isinstance(obj, type(sys)):  # Skip modules
            result.append({"name": name, "type": type(obj).__name__})
print(json.dumps(result))
"""
        return await session_manager.run_simple_code(notebook_path, code)

    @mcp.tool()
    @validated_tool(GetVariableManifestArgs)
    async def get_variable_manifest(notebook_path: str):
        """
        [VARIABLE DASHBOARD] Lightweight manifest of all kernel variables.
        Returns name, type, and memory size for each variable (optimized for UI polling).
        
        **Use Case**: VS Code extension can poll this after each execution to populate
        a Variable Explorer sidebar, giving humans visibility into the agent's kernel state.
        
        **Performance**: Much lighter than list_variables() - includes memory size for sorting.
        
        Returns:
            JSON array: [{"name": "df", "type": "DataFrame", "size": "2.4 MB"}, ...]
        """
        code = """
import json
import sys

def get_size_str(obj):
    '''Get human-readable size string'''
    try:
        # Whitelist safe primitive/container types for deep inspection
        safe_types = (str, bytes, bytearray, list, tuple, set, dict, int, float, bool, complex)
        type_str = str(type(obj))

        # Avoid calling potentially dangerous custom __sizeof__ implementations
        if not isinstance(obj, safe_types) and 'pandas' not in type_str and 'numpy' not in type_str:
            return "?"

        # Try to get actual memory usage for safe/known types
        size = sys.getsizeof(obj)

        # For containers, estimate recursively (limit depth to avoid heavy work)
        if hasattr(obj, '__len__') and not isinstance(obj, (str, bytes, bytearray)):
            try:
                if hasattr(obj, 'memory_usage') and 'pandas' in type_str:  # pandas DataFrame/Series
                    size = int(obj.memory_usage(deep=True).sum())
                elif isinstance(obj, (list, tuple, set)):
                    size += sum(sys.getsizeof(item) for item in list(obj)[:100])  # Sample first 100
                elif isinstance(obj, dict):
                    items = list(obj.items())[:100]
                    size += sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in items)
            except Exception:
                # If any inspection errors, return unknown size
                return "?"

        # Format size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"
    except Exception:
        return "?"

manifest = []
for name in sorted(dir()):
    if not name.startswith('_'):
        try:
            obj = globals()[name]
            if not isinstance(obj, type(sys)):  # Skip modules
                manifest.append({
                    "name": name,
                    "type": type(obj).__name__,
                    "size": get_size_str(obj)
                })
        except:
            pass

print(json.dumps(manifest))
"""
        return await session_manager.run_simple_code(notebook_path, code)

    @mcp.tool()
    @validated_tool(InspectVariableArgs)
    async def inspect_variable(notebook_path: str, variable_name: str):
        """
        Surgical Inspection: Returns a human-readable markdown summary of a variable.
        
        Agent Use Case: 
        - Peek at DataFrames without loading 1GB of data into context
        - Inspect lists, dicts, models without full dumps
        - Get shape, columns, dtypes, and head(3) for DataFrames
        
        Returns: Markdown-formatted summary suitable for LLM consumption
        """
        # 1. Input Validation (Prevent Injection)
        if not variable_name.isidentifier():
            return f"Error: '{variable_name}' is not a valid Python identifier. Cannot inspect."

        # SECURITY FIX: Use pre-defined helper function instead of sending code blocks
        # Logic is defined in session.py startup_code as _mcp_inspect(name)
        code = f"_mcp_inspect('{variable_name}')"
        
        return await session_manager.run_simple_code(notebook_path, code)

    @mcp.tool()
    async def search_dataframe_columns(notebook_path: str, dataframe_name: str, pattern: str):
        """
        [DUH FIX #5] Search DataFrame columns by regex pattern.
        
        For wide DataFrames (genomics data with 5000+ columns),
        use this to find specific columns without loading all column names.
        
        Args:
            notebook_path: Path to notebook with running kernel
            dataframe_name: Name of the DataFrame variable
            pattern: Regex pattern to search for (case-insensitive)
        
        Returns:
            Markdown list of matching columns with their dtypes
            
        Example:
            search_dataframe_columns("analysis.ipynb", "df_genes", "BRCA")
            # Returns: List of columns containing 'BRCA' (e.g., BRCA1, BRCA2, BRCA1_expression)
        """
        # Input Validation
        if not dataframe_name.isidentifier():
            return f"Error: '{dataframe_name}' is not a valid Python identifier."
        
        # Escape single quotes in pattern for safety
        safe_pattern = pattern.replace("'", "\\'").replace("\\", "\\\\")
        
        code = f"_mcp_search_columns('{dataframe_name}', '{safe_pattern}')"
        
        return await session_manager.run_simple_code(notebook_path, code)
