"""Lightweight observability shim for tests and local dev.
Provides get_logger() and get_tracer() used across the codebase.
"""
import logging
from contextlib import contextmanager
import uuid


class _SimpleLogger:
    def __init__(self, base_logger):
        self._base = base_logger

    def _safe(self, method, msg, *args, **kwargs):
        # Accept and ignore structured kwargs for compatibility
        try:
            return getattr(self._base, method)(msg, *args)
        except Exception:
            try:
                return getattr(self._base, method)(str(msg))
            except Exception:
                pass

    def info(self, msg, *args, **kwargs):
        return self._safe("info", msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        return self._safe("warning", msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        return self._safe("debug", msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        return self._safe("error", msg, *args, **kwargs)


def get_logger(name: str = __name__):
    return _SimpleLogger(logging.getLogger(name))


@contextmanager
def get_tracer(name: str = "mcp.tracer"):
    """A no-op tracer context manager used in tests/when tracing is disabled."""
    yield None


def generate_request_id() -> str:
    """Return a short, unique request id for correlating logs in tests/local dev."""
    return uuid.uuid4().hex[:8]
