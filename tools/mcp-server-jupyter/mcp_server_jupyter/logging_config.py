import logging
import sys

try:
    # Some distributions expose this as python_json_logger or pythonjsonlogger
    from python_json_logger import jsonlogger
except Exception:
    try:
        # pythonjsonlogger v3.x moved jsonlogger to pythonjsonlogger.json
        from pythonjsonlogger.json import JsonFormatter as _JsonFormatter
        # Create a shim module-like object for compatibility
        class jsonlogger:
            JsonFormatter = _JsonFormatter
    except Exception:
        try:
            # pythonjsonlogger v2.x (deprecated path)
            from pythonjsonlogger import jsonlogger  # noqa: F401
        except Exception:
            jsonlogger = None


def setup_logging():
    """Configures structured JSON logging for the application."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Use a handler that outputs to stderr so stdout remains available for
    # structured JSON-RPC communication over stdio (important for harness tests).
    logHandler = logging.StreamHandler(sys.stderr)

    # Use a JSON formatter when available, otherwise a plain formatter
    if jsonlogger is not None:
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s %(module)s %(funcName)s"
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s %(module)s %(funcName)s"
        )

    logHandler.setFormatter(formatter)

    # Avoid adding duplicate handlers
    if not logger.handlers:
        logger.addHandler(logHandler)
