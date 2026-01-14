"""
Input validation utilities for notebook operations.

These functions provide centralized validation for common inputs
to ensure consistent error handling across the codebase.
"""

import os
import asyncio
from pathlib import Path
from typing import Optional, Tuple, Any


class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass


def validate_notebook_path(notebook_path: str, must_exist: bool = False) -> Path:
    """
    Validate a notebook path.
    
    Args:
        notebook_path: Path to validate
        must_exist: If True, path must point to existing file
        
    Returns:
        Resolved Path object
        
    Raises:
        ValidationError: If validation fails
    """
    if not notebook_path:
        raise ValidationError("Notebook path cannot be empty")
    
    if not isinstance(notebook_path, str):
        raise ValidationError(f"Notebook path must be a string, got {type(notebook_path).__name__}")
    
    path = Path(notebook_path).resolve()
    
    # Check extension
    if path.suffix.lower() != '.ipynb':
        raise ValidationError(f"Notebook must have .ipynb extension, got '{path.suffix}'")
    
    # Check if it exists (when required)
    if must_exist and not path.exists():
        raise ValidationError(f"Notebook not found: {notebook_path}")
    
    # Check if it's a file (not a directory)
    if path.exists() and path.is_dir():
        raise ValidationError(f"Path is a directory, not a file: {notebook_path}")
    
    return path

def check_code_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """
    Check Python code for syntax errors using the AST parser.
    
    Args:
        code: Python source code string
        
    Returns:
        Tuple (is_valid, error_message)
    """
    import ast
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}\n>>> {e.text.strip() if e.text else ''}"
    except Exception as e:
        return False, f"Error parsing code: {str(e)}"



def validate_cell_index(index: int, total_cells: int, allow_negative: bool = True) -> int:
    """
    Validate and normalize a cell index.
    
    Args:
        index: Cell index to validate
        total_cells: Total number of cells in notebook
        allow_negative: Whether to allow Python-style negative indexing
        
    Returns:
        Normalized (positive) index
        
    Raises:
        ValidationError: If index is out of range
    """
    if not isinstance(index, int):
        raise ValidationError(f"Cell index must be an integer, got {type(index).__name__}")
    
    if total_cells == 0:
        raise ValidationError("Notebook has no cells")
    
    # Normalize negative index
    actual_index = index
    if index < 0:
        if not allow_negative:
            raise ValidationError(f"Negative indices not allowed, got {index}")
        actual_index = total_cells + index
    
    # Check bounds
    if actual_index < 0 or actual_index >= total_cells:
        raise ValidationError(
            f"Cell index {index} out of range. "
            f"Valid range: 0 to {total_cells - 1} (or -{total_cells} to -1)"
        )
    
    return actual_index


def validate_cell_type(cell_type: str) -> str:
    """
    Validate cell type.
    
    Args:
        cell_type: Cell type to validate
        
    Returns:
        Normalized cell type
        
    Raises:
        ValidationError: If cell type is invalid
    """
    valid_types = {'code', 'markdown', 'raw'}
    
    if not isinstance(cell_type, str):
        raise ValidationError(f"Cell type must be a string, got {type(cell_type).__name__}")
    
    normalized = cell_type.lower().strip()
    
    if normalized not in valid_types:
        raise ValidationError(
            f"Invalid cell type '{cell_type}'. "
            f"Valid types: {', '.join(sorted(valid_types))}"
        )
    
    return normalized


def validate_cell_content(content: Any) -> str:
    """
    Validate and normalize cell content.
    
    Args:
        content: Cell content to validate
        
    Returns:
        Normalized content string
        
    Raises:
        ValidationError: If content is invalid
    """
    if content is None:
        return ""
    
    if not isinstance(content, str):
        try:
            content = str(content)
        except Exception:
            raise ValidationError(f"Cell content must be a string, got {type(content).__name__}")
    
    # Check for null bytes (can corrupt JSON)
    if '\x00' in content:
        raise ValidationError("Cell content cannot contain null bytes")
    
    return content


def validate_initial_cells(initial_cells: Optional[list]) -> list:
    """
    Validate initial cells specification for notebook creation.
    
    Args:
        initial_cells: List of cell specifications
        
    Returns:
        Validated and normalized cell list
        
    Raises:
        ValidationError: If cells specification is invalid
    """
    if initial_cells is None:
        return []
    
    if not isinstance(initial_cells, list):
        raise ValidationError(
            f"initial_cells must be a list, got {type(initial_cells).__name__}"
        )
    
    validated = []
    for i, cell_spec in enumerate(initial_cells):
        if not isinstance(cell_spec, dict):
            raise ValidationError(
                f"Cell specification at index {i} must be a dict, got {type(cell_spec).__name__}"
            )
        
        cell_type = cell_spec.get('type', 'code')
        content = cell_spec.get('content', '')
        
        try:
            validated_type = validate_cell_type(cell_type)
            validated_content = validate_cell_content(content)
        except ValidationError as e:
            raise ValidationError(f"Invalid cell at index {i}: {e}")
        
        validated.append({
            'type': validated_type,
            'content': validated_content
        })
    
    return validated


def validate_kernel_name(kernel_name: str) -> str:
    """
    Validate kernel name.
    
    Args:
        kernel_name: Kernel name to validate
        
    Returns:
        Validated kernel name
        
    Raises:
        ValidationError: If kernel name is invalid
    """
    if not isinstance(kernel_name, str):
        raise ValidationError(f"Kernel name must be a string, got {type(kernel_name).__name__}")
    
    if not kernel_name.strip():
        raise ValidationError("Kernel name cannot be empty")
    
    # Basic sanity check on kernel name format
    # Kernel names should be alphanumeric with underscores, hyphens, and dots
    import re
    if not re.match(r'^[\w\-\.]+$', kernel_name):
        # Just log a warning, don't reject - kernel names can be unusual
        import logging
        logging.getLogger(__name__).warning(
            f"Unusual kernel name format: '{kernel_name}'"
        )
    
    return kernel_name


def validate_venv_path(venv_path: Optional[str]) -> Optional[Path]:
    """
    Validate virtual environment path.
    
    Args:
        venv_path: Path to virtual environment
        
    Returns:
        Resolved Path object or None
        
    Raises:
        ValidationError: If path is invalid
    """
    if not venv_path:
        return None
    
    if not isinstance(venv_path, str):
        raise ValidationError(f"venv_path must be a string, got {type(venv_path).__name__}")
    
    path = Path(venv_path).resolve()
    
    if not path.exists():
        raise ValidationError(f"Virtual environment not found: {venv_path}")
    
    if not path.is_dir():
        raise ValidationError(f"Virtual environment path is not a directory: {venv_path}")
    
    # Check for typical venv structure
    # Windows: Scripts/python.exe, Unix: bin/python
    scripts_dir = path / 'Scripts'
    bin_dir = path / 'bin'
    
    if not (scripts_dir.exists() or bin_dir.exists()):
        raise ValidationError(
            f"Path doesn't appear to be a valid virtual environment: {venv_path}. "
            "Expected 'Scripts' (Windows) or 'bin' (Unix) directory."
        )
    
    return path


def safe_result(func):
    """
    Decorator that catches exceptions and returns error strings.
    
    Useful for MCP tool functions that should return error messages
    instead of raising exceptions.
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValidationError as e:
            return f"Error: {e}"
        except FileNotFoundError as e:
            return f"Error: File not found - {e}"
        except IndexError as e:
            return f"Error: Index out of range - {e}"
        except PermissionError as e:
            return f"Error: Permission denied - {e}"
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Unexpected error in tool function")
            return f"Error: Unexpected error - {e}"
    
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def safe_result_async(func):
    """
    Async version of safe_result decorator.
    """
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ValidationError as e:
            return f"Error: {e}"
        except FileNotFoundError as e:
            return f"Error: File not found - {e}"
        except IndexError as e:
            return f"Error: Index out of range - {e}"
        except PermissionError as e:
            return f"Error: Permission denied - {e}"
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Unexpected error in async tool function")
            return f"Error: Unexpected error - {e}"
    
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


# --- Pydantic-backed validated tool decorator ---
from functools import wraps
from pydantic import ValidationError as PydanticValidationError
from src.observability import get_logger, generate_request_id

logger = get_logger()


def validated_tool(model_class):
    """
    Decorator that:
    1. Generates a trace ID for the tool call.
    2. Validates inputs against Pydantic model.
    3. Logs start/finish/error with structured data.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            req_id = generate_request_id()
            tool_name = func.__name__

            # 1. Log Entry
            logger.info("tool_call_start", tool=tool_name, request_id=req_id)

            try:
                # 2. Validate (offload to thread pool to avoid blocking the event loop)
                from src.utils import offload_validation
                validated_data = await offload_validation(model_class, **kwargs)

                # 3. Execute
                result = await func(**validated_data.model_dump()) if asyncio.iscoroutinefunction(func) else func(**validated_data.model_dump())

                # 4. Log Success
                logger.info("tool_call_success", tool=tool_name, request_id=req_id)
                return result

            except PydanticValidationError as e:
                logger.warning("tool_validation_failed", tool=tool_name, errors=e.errors(), request_id=req_id)
                return f"Input Error: {str(e)}"  # Return friendly error to Agent
            except Exception as e:
                logger.error("tool_execution_failed", tool=tool_name, error=str(e), request_id=req_id)
                raise e

        return wrapper
    return decorator
