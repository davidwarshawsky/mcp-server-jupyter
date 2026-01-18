# [FINAL PUNCH LIST #6] Validated configuration with Pydantic
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict, field_validator
from typing import Optional
import sys

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", case_sensitive=True)
    
    # Server
    MCP_HOST: str = Field(default="127.0.0.1", description="Server bind address")
    MCP_PORT: int = Field(default=3000, ge=1024, le=65535, description="Server port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Security
    MCP_SESSION_TOKEN: Optional[str] = Field(default=None, description="Auth token (auto-generated)")
    MCP_PACKAGE_ALLOWLIST: Optional[str] = Field(default=None, description="Allowed packages CSV")

    # Resources
    MCP_MAX_KERNELS: int = Field(default=10, ge=1, le=100, description="Max concurrent kernels")
    MCP_MEMORY_LIMIT_BYTES: int = Field(default=8 * 1024**3, ge=128*1024**2, description="RAM limit per kernel")
    MCP_IO_POOL_SIZE: int = Field(default=4, ge=1, le=32, description="I/O thread pool size")

    # Asset Management
    MCP_ASSET_MAX_AGE_HOURS: int = Field(default=24, ge=1, le=720, description="Asset retention hours")
    MCP_ALLOWED_ROOT: Optional[str] = Field(default=None, description="Docker volume mount root")

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = Field(default=None, description="OpenTelemetry endpoint")
    
    # Development
    MCP_DEV_MODE: bool = Field(default=False, description="Development mode flag")
    
    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}, got '{v}'")
        return v_upper
    
    @field_validator("MCP_PACKAGE_ALLOWLIST")
    @classmethod
    def validate_package_allowlist(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        packages = [p.strip() for p in v.split(",") if p.strip()]
        for pkg in packages:
            if not pkg.replace("-", "").replace("_", "").isalnum():
                raise ValueError(f"Invalid package name: '{pkg}'")
        return v


def load_and_validate_settings() -> Settings:
    """Load and validate environment variables. Exits on error."""
    try:
        return Settings()
    except Exception as e:
        import structlog
        logger = structlog.get_logger()
        logger.critical("[CONFIG] Validation failed", error=str(e))
        print(f"\n❌ Configuration Error:\n{e}\n", file=sys.stderr)
        print("See ENVIRONMENT_VARIABLES.md for valid values.\n", file=sys.stderr)
        sys.exit(1)


# Singleton instance
settings = load_and_validate_settings()
