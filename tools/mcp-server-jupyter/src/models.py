from pydantic import BaseModel, Field, field_validator, FilePath, constr
from pathlib import Path
from typing import Optional

class SecureBaseModel(BaseModel):
    class Config:
        # Forbid extra fields to prevent payload bloating attacks
        extra = "forbid"

class StartKernelArgs(SecureBaseModel):
    notebook_path: str = Field(..., description="Absolute path to the notebook")
    venv_path: Optional[str] = None
    docker_image: Optional[str] = None
    timeout: int = Field(default=300, ge=10, le=3600) # Constrain timeout

    @field_validator('notebook_path')
    @classmethod
    def validate_path(cls, v):
        p = Path(v)
        if '..' in p.parts:
            raise ValueError("Path traversal detected")
        if not p.is_absolute():
            # In production, you might enforce absolute paths or resolve strictly relative to a safe root
            pass
        return str(p)

class RunCellArgs(SecureBaseModel):
    notebook_path: str
    index: int = Field(..., ge=0)
    code_override: Optional[str] = Field(None, max_length=100_000) # Prevent memory DoS
