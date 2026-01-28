import warnings
from .duckdb_utils import execute_duckdb_query as _execute_duckdb_query

warnings.warn(
    "src.security is deprecated and will be removed. Use src.duckdb_utils.execute_duckdb_query instead.",
    DeprecationWarning,
)

# Re-export for backwards compatibility
def execute_duckdb_query(query: str, params: list = None):
    return _execute_duckdb_query(query, params)
