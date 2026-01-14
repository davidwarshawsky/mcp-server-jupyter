import sys
import logging
import structlog
import uuid
import contextvars
from typing import Any, Dict

# Context variables for tracing (Request ID, Session ID)
request_id_ctx = contextvars.ContextVar("request_id", default="startup")


def configure_logging(level="INFO"):
    """
    Configures structured JSON logging for production.
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # If running in a TTY (dev), keep colors. If prod (pipe/file), use JSON.
    if sys.stderr.isatty():
        processors = shared_processors + [structlog.dev.ConsoleRenderer()]
    else:
        processors = shared_processors + [structlog.processors.JSONRenderer()]

    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Redirect standard logging to structlog
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)
    logging.getLogger().handlers = []  # Clear default handlers

    # Hook into stdlib logger
    def logger_factory(name):
        return structlog.get_logger(logger_name=name)

    return structlog.get_logger()


def get_logger(name=None):
    return structlog.get_logger(name)


def generate_request_id():
    req_id = str(uuid.uuid4())
    request_id_ctx.set(req_id)
    return req_id
