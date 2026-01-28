"""
Simple logging wrapper for local development.
Replaces complex OpenTelemetry with standard Python logging.
"""

import logging
import sys


def get_logger(name: str = __name__):
    """Get a standard Python logger that writes to stderr."""
    logger = logging.getLogger(name)
    # Ensure it writes to stderr for VS Code Output Channel capture
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter('[%(levelname)s] %(name)s: %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def get_tracer(name: str = "mcp.tracer"):
    """No-op tracer for compatibility."""
    return None


def generate_request_id():
    """Generate a unique request ID."""
    return str(uuid.uuid4())
