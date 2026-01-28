def execute_duckdb_query(query: str, params: list = None):
    """
    Executes a DuckDB query safely using parameterized statements.
    """
    try:
        import pandas as pd
        import duckdb

        # Connect to an in-memory DuckDB database
        con = duckdb.connect(database=":memory:", read_only=False)

        # Use parameters to prevent SQL injection
        if params:
            result_df = con.execute(query, params).fetchdf()
        else:
            result_df = con.execute(query).fetchdf()

        con.close()

        return result_df
    except ImportError as e:
        raise RuntimeError(
            "DuckDB features require optional dependencies. Install with: "
            "pip install mcp-server-jupyter[superpowers]"
        ) from e
    except duckdb.Error as e:
        # Handle DuckDB execution errors
        print(f"DuckDB error: {e}")
        raise
