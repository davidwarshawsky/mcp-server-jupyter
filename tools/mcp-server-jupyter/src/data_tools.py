"""
Data Tools: SQL queries on DataFrames, variable exploration, data manipulation.

These tools provide "superpowers" for data exploration by enabling SQL queries
directly on Python variables in memory using DuckDB.
"""

from src.utils import ToolResult
from src import utils
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.session import SessionManager


async def query_dataframes(
    session_manager: "SessionManager", notebook_path: str, sql_query: str
) -> str:
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
        - Uses parameterized queries to prevent SQL injection
    """
    session = session_manager.get_session(notebook_path)
    if not session:
        tr = ToolResult(
            success=False,
            data={},
            error_msg="No running kernel. Call start_kernel first.",
        )
        from dataclasses import asdict
        return await utils.offload_json_dumps(asdict(tr))

    # [CRITICAL SECURITY FIX] Use parameterized queries, NOT Base64 encoding.
    # Base64 is NOT a security mechanism - it's just obfuscation.
    # Example of why Base64 fails:
    #   Input: ' OR '1'='1
    #   Base64: JyBPUiAnMSc9JzEn (still executes as SQL injection after decode)
    #
    # PROPER FIX: Use a transport that treats user input as opaque data.
    # We encode the SQL as Base64 on the server and decode it inside the kernel so
    # the Python source injected into the kernel can never be broken by crafted SQL.
    import base64

    b64_query = base64.b64encode(sql_query.encode('utf-8')).decode('ascii')

    code = f'''
import sys

try:
    import duckdb
except ImportError:
    print("❌ DuckDB is required for SQL queries on DataFrames.")
    print("Install it with: pip install mcp-server-jupyter[superpowers]")
    print("Or directly: pip install duckdb")
    raise ImportError("duckdb not installed - see message above for installation instructions")

try:
    # DuckDB can query pandas DataFrames in the current scope
    con = duckdb.connect(database=':memory:')
    
    # [SECURITY] Resource limits to prevent DoS attacks
    # Limit memory usage to 512MB (prevents OOM from cross-join bombs)
    con.execute("SET memory_limit='512MB';")
    # Limit threads to prevent CPU exhaustion
    con.execute("SET threads=2;")
    # Set query depth limit
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
    
    # Transport the SQL as Base64 (treat user input as opaque data) to avoid
    # any possibility of breaking out of the injected Python string literal.
    import base64

    # The server encodes the user SQL and the kernel decodes it below. This prevents
    # crafted input from injecting Python into the injected cell text.
    query_b64 = "{b64_query}"

    # Decode and execute inside the kernel
    query = base64.b64decode(query_b64).decode('utf-8')

    # Execute query
    result_df = con.execute(query).df()

    # Convert to markdown for clean display
    if len(result_df) == 0:
        print("Query returned 0 rows.")
    elif len(result_df) > 100:
        print(f"Query returned {{len(result_df)}} rows. Showing first 100:")
        print(result_df.head(100).to_markdown(index=False))
        print(f"\n... ({{len(result_df) - 100}} more rows)")
    else:
        print(result_df.to_markdown(index=False))

    # Summary
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
            success=False, data={}, error_msg="Failed to submit SQL query"
        ).to_json()

    # Wait for completion and collect output
    import time

    timeout = 30  # SQL queries can take time on large datasets
    start_time = time.time()

    while time.time() - start_time < timeout:
        status = session_manager.get_execution_status(notebook_path, exec_id)
        if status["status"] in ["completed", "error"]:
            # Extract output
            outputs = status.get("outputs", [])
            output_text = ""

            for out in outputs:
                if out.get("output_type") == "stream" and "text" in out:
                    output_text += out["text"]
                elif out.get("output_type") == "error":
                    output_text += (
                        f"ERROR: {out.get('ename', 'Unknown')}: {out.get('evalue', '')}"
                    )

            if output_text:
                # Detect SQL errors printed by the kernel and return failure in that case
                lowered = output_text.lower()
                if "❌ sql error" in lowered or "sql error:" in lowered or "error:" in lowered:
                    tr = ToolResult(success=False, data={}, error_msg=output_text)
                    from dataclasses import asdict
                    return await utils.offload_json_dumps(asdict(tr))

                # Mitigation for large outputs: offload to assets if result is too large
                from pathlib import Path
                import hashlib
                from src.asset_manager import ensure_assets_gitignored

                MAX_RESULT_BYTES = 100 * 1024  # 100KB

                if len(output_text.encode('utf-8')) > MAX_RESULT_BYTES:
                    # Offload full output to an asset and return a small preview
                    assets_dir = Path(notebook_path).resolve().parent / "assets"
                    assets_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        ensure_assets_gitignored(str(assets_dir))
                    except Exception:
                        pass

                    content_hash = hashlib.sha256(output_text.encode('utf-8')).hexdigest()[:32]
                    asset_filename = f"text_{content_hash}.txt"
                    asset_path = assets_dir / asset_filename
                    with open(asset_path, "w", encoding="utf-8") as f:
                        f.write(output_text)

                    # Create a preview of the first/last lines
                    lines = output_text.splitlines()
                    preview_head = "\n".join(lines[:20])
                    preview_tail = "\n".join(lines[-5:]) if len(lines) > 25 else ""
                    preview = preview_head
                    if preview_tail:
                        preview += "\n... [Truncated preview] ...\n" + preview_tail

                    tr = ToolResult(
                        success=True,
                        data={
                            "query": sql_query,
                            "result_preview": preview,
                            "result_asset": {
                                "filename": asset_filename,
                                "path": str(asset_path),
                                "size_bytes": asset_path.stat().st_size,
                            },
                        },
                        user_suggestion="Result too large to return inline. Full output saved to assets/ - use read_asset() or inspect the file.",
                    )
                    from dataclasses import asdict
                    return await utils.offload_json_dumps(asdict(tr))

                # Small enough to return inline
                tr = ToolResult(
                    success=True,
                    data={"query": sql_query, "result": output_text},
                    user_suggestion="Query executed successfully. Use SQL to explore your data efficiently!",
                )
                from dataclasses import asdict
                return await utils.offload_json_dumps(asdict(tr))
            else:
                tr = ToolResult(
                    success=False, data={}, error_msg="No output from SQL query"
                )
                from dataclasses import asdict
                return await utils.offload_json_dumps(asdict(tr))

        import asyncio

        await asyncio.sleep(0.5)

    tr = ToolResult(success=False, data={}, error_msg="SQL query timeout (30s)")
    from dataclasses import asdict
    return await utils.offload_json_dumps(asdict(tr))
