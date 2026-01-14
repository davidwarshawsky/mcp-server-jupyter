from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # Server
    MCP_HOST: str = "127.0.0.1"
    MCP_PORT: int = 3000
    LOG_LEVEL: str = "INFO"

    # Resources
    MCP_MEMORY_LIMIT_BYTES: int = Field(default=8 * 1024**3, description="RAM limit per kernel in bytes")
    MCP_IO_POOL_SIZE: int = Field(default=4, description="Threads for JSON serialization")

    # Security
    SESSION_SECRET_KEY: str = Field(default="", description="If set, overrides ephemeral key for checkpoints")

    class Config:
        env_file = ".env"

settings = Settings()
