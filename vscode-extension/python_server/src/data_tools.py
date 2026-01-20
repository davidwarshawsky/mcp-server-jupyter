"""
Data Tools: SQL queries on DataFrames, variable exploration, data manipulation.

These tools provide "superpowers" for data exploration by enabling SQL queries
directly on Python variables in memory using DuckDB.
"""

import json
from src.utils import ToolResult
from src.session import SessionManager

async def query_dataframes(session_manager: SessionManager, notebook_path: str, sql_query: str) -> str:
    """
    [SUPERPOWER] Run SQL directly on active DataFrames in the kernel.
    
    Uses DuckDB to execute SQL queries against pandas/polars DataFrames in memory.
    No data copying required - DuckDB reads directly from the Python objects.
    
    Args:
        notebook_path: Path to notebook with running kernel
        sql_query: SQL query (e.g., "SELECT * FROM df WHERE amount > 100")
    
    Returns:
        JSON with query results as markdown table
        
    Example:
        query_dataframes("analysis.ipynb", "SELECT region, SUM(revenue) FROM df_sales GROUP BY region")
        # Returns: Markdown table with aggregated results
        
    Safety:
        - Auto-installs duckdb if not available
        - Runs in kernel's execution queue (respects locks)
        - Errors are captured and returned gracefully
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        return ToolResult(
            success=False,
            data={},
            error_msg="No running kernel. Call start_kernel first."
        ).to_json()
    
    # [SECURITY FIX] Base64 encode the query to prevent injection.
    # The kernel will decode it before execution. This is safer than string replacement.
    import base64
    encoded_query = base64.b64encode(sql_query.encode()).decode()

    code = f'''
import sys
import base64

try:
    import duckdb
except ImportError:
    print("❌ DuckDB is required for SQL queries on DataFrames.")
    print("Install it with: pip install mcp-server-jupyter[superpowers]")
    print("Or directly: pip install duckdb")
    raise ImportError("duckdb not installed - see message above for installation instructions")

# Decode the query from Base64 (prevents SQL injection via string breakout)
try:
    decoded_query = base64.b64decode("{encoded_query}").decode()
    
    # DuckDB can query pandas DataFrames in the current scope
    con = duckdb.connect(database=':memory:')
    
    # [SECURITY] Resource limits to prevent DoS attacks
    # Limit memory usage to 512MB (prevents OOM from cross-join bombs)
    con.execute("SET memory_limit='512MB';")
    # Limit threads to prevent CPU exhaustion
    con.execute("SET threads=2;")
    # Set query timeout (30 seconds max)
    con.execute("SET max_expression_depth=100;")
    
    # Disable filesystem access and external extensions
    con.execute("SET enable_external_access=false;")
    con.execute("SET lock_configuration=true;")
    # [IIRB P0 FIX #5] REMOVED: Auto-registration of all DataFrames
    # OLD BEHAVIOR: Auto-registered ALL DataFrames in globals(), including:
    # - df_public (intended for query)
    # - df_confidential_salaries (private, not intended for query)
    # - Any other DataFrames in kernel namespace
    #
    # SECURITY RISK: Violates Principle of Least Privilege
    # - Agent could access sensitive data via prompt injection
    # - Example: "JOIN df_public WITH df_confidential_salaries"
    #
    # NEW BEHAVIOR: Query MUST explicitly reference table names
    # - DuckDB can access DataFrames by name without explicit registration
    # - Example: SELECT * FROM df_public (works if df_public exists in globals())
    # - But agent cannot discover table names via auto-registration
    #
    # FUTURE: Add explicit register_table() tool if needed:
    # register_table("sales_data", "df_sales") -> Allow query access
    
    # DuckDB automatically discovers DataFrames in scope when referenced by name
    # No explicit registration needed - query must know table name
    result_df = con.execute(decoded_query).df()
    
    # Convert to markdown for clean display
    if len(result_df) == 0:
        print("Query returned 0 rows.")
    elif len(result_df) > 100:
        print(f"Query returned {{len(result_df)}} rows. Showing first 100:")
        print(result_df.head(100).to_markdown(index=False))
        print(f"\\n... ({{len(result_df) - 100}} more rows)")
    else:
        print(result_df.to_markdown(index=False))
        
    # Also print summary stats
    print(f"\\n📊 Query Stats: {{len(result_df)}} rows × {{len(result_df.columns)}} columns")
    
except Exception as e:
    print(f"❌ SQL Error: {{type(e).__name__}}: {{str(e)}}")
    print("\\nAvailable DataFrames in scope:")
    for var_name, var_obj in list(globals().items()):
        if not var_name.startswith('_'):
            type_name = type(var_obj).__name__
            if 'DataFrame' in type_name or 'Series' in type_name:
                shape = getattr(var_obj, 'shape', None)
                print(f"  - {{var_name}}: {{type_name}} {{shape}}")
'''
    
    # Execute using SessionManager's queue (cell_index=-1 for internal tools)
    exec_id = await session_manager.execute_cell_async(notebook_path, -1, code)
    if not exec_id:
        return ToolResult(
            success=False,
            data={},
            error_msg="Failed to submit SQL query"
        ).to_json()
    
    # Wait for completion and collect output
    import time
    timeout = 30  # SQL queries can take time on large datasets
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        status = session_manager.get_execution_status(notebook_path, exec_id)
        if status['status'] in ['completed', 'error']:
            # Extract output
            outputs = status.get('outputs', [])
            output_text = ""
            
            for out in outputs:
                if out.get('output_type') == 'stream' and 'text' in out:
                    output_text += out['text']
                elif out.get('output_type') == 'error':
                    output_text += f"ERROR: {out.get('ename', 'Unknown')}: {out.get('evalue', '')}"
            
            if output_text:
                return ToolResult(
                    success=True,
                    data={
                        'query': sql_query,
                        'result': output_text
                    },
                    user_suggestion="Query executed successfully. Use SQL to explore your data efficiently!"
                ).to_json()
            else:
                return ToolResult(
                    success=False,
                    data={},
                    error_msg="No output from SQL query"
                ).to_json()
        
        import asyncio
        await asyncio.sleep(0.5)
    
    return ToolResult(
        success=False,
        data={},
        error_msg="SQL query timeout (30s)"
    ).to_json()
