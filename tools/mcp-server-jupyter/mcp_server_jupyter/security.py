import warnings
from pathlib import Path

warnings.warn(
    "src.security is deprecated and will be removed. Use src.duckdb_utils.execute_duckdb_query instead.",
    DeprecationWarning,
)

# Re-export for backwards compatibility
def execute_duckdb_query(query: str, params: list = None):
    from .duckdb_utils import execute_duckdb_query as _execute_duckdb_query
    return _execute_duckdb_query(query, params)


def validate_path(filename: str, base_dir: Path) -> Path:
    """Validate a filename is within base_dir and prevent path traversal."""
    if not filename:
        raise ValueError("Filename is required")

    base_dir = Path(base_dir).resolve()
    candidate = (base_dir / filename).resolve()

    if not str(candidate).startswith(str(base_dir)):
        raise PermissionError("Path traversal attempt blocked")

    return candidate
