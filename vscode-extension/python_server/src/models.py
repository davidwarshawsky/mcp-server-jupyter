from pydantic import BaseModel, Field, field_validator, FilePath, constr, ConfigDict
from pathlib import Path
from typing import Optional

class SecureBaseModel(BaseModel):
    # Use ConfigDict to satisfy Pydantic v2 recommendations
    model_config = ConfigDict(extra="forbid")

class StartKernelArgs(SecureBaseModel):
    notebook_path: str = Field(..., description="Absolute path to the notebook")
    venv_path: Optional[str] = None
    docker_image: Optional[str] = None
    timeout: int = Field(default=300, ge=10, le=3600) # Constrain timeout
    agent_id: Optional[str] = None  # Optional agent identifier to isolate CWD

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
    task_id_override: Optional[str] = Field(None, max_length=100)  # Client-generated execution ID
