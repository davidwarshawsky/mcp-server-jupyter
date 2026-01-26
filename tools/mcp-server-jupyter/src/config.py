import os
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict
from typing import Literal


class ServerConfig(BaseSettings):
    """Manages application-wide configuration using environment variables."""

    # Server settings
    HOST: str = Field("127.0.0.1", frozen=True)
    PORT: int = Field(default=8000, ge=1024, le=65535)
    LOG_LEVEL: Literal["debug", "info", "warning", "error", "critical"] = Field(
        default="info"
    )

    # Kubernetes settings
    K8S_NAMESPACE: str = "default"

    # Operational limits (defaults provided for tests/contracts)
    MCP_MEMORY_LIMIT_BYTES: int = int(os.getenv("MCP_MEMORY_LIMIT_BYTES", str(8 * 1024 * 1024 * 1024)))
    MCP_IO_POOL_SIZE: int = int(os.getenv("MCP_IO_POOL_SIZE", "4"))

    # In a real app, you'd have more, like database URLs, external API keys, etc.

    # Use Pydantic v2 style configuration to avoid deprecation warnings
    # See: https://docs.pydantic.dev/latest/usage/settings/#BaseSettings
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


# Instantiate a single config object to be used across the application
config = ServerConfig()

# Backwards compatibility: some modules import `settings` variable
settings = config

# For tests that expect to construct settings from environment and get
# pydantic.ValidationError on invalid values, provide a thin factory that
# validates using a simple pydantic BaseModel built from current environment.
from pydantic import BaseModel, ValidationError
from pydantic import conint


class _EnvValidatedSettings(BaseModel):
    PORT: conint(ge=1024, le=65535) = 8000
    LOG_LEVEL: Literal["debug", "info", "warning", "error", "critical"] = "info"


def Settings():
    """Factory that builds a validated settings object from environment.

    Returns a pydantic BaseModel instance or raises ValidationError.
    """
    port_val = os.getenv("MCP_PORT") or os.getenv("PORT")
    log_level = os.getenv("LOG_LEVEL") or os.getenv("MCP_LOG_LEVEL") or "info"

    data = {}
    if port_val is not None:
        try:
            data["PORT"] = int(port_val)
        except Exception:
            # Let pydantic raise a validation error for non-int values
            data["PORT"] = port_val
    else:
        data["PORT"] = 8000

    data["LOG_LEVEL"] = log_level

    return _EnvValidatedSettings(**data)


def load_and_validate_settings():
    """Return validated settings object and provide helper accessors.

    Provides convenience accessors used throughout the codebase (legacy compatibility).
    """
    # Ensure MCP_DATA_DIR exists and is a Path
    data_dir = os.getenv("MCP_DATA_DIR") or getattr(config, "MCP_DATA_DIR", None)
    if data_dir:
        from pathlib import Path

        p = Path(data_dir)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # Attach helper (use object.__setattr__ to avoid Pydantic complaints)
        object.__setattr__(config, "get_data_dir", lambda: p)
    else:
        # Fallback to ~/.mcp
        from pathlib import Path

        p = Path.home() / ".mcp"
        p.mkdir(parents=True, exist_ok=True)
        object.__setattr__(config, "get_data_dir", lambda: p)

    return config
