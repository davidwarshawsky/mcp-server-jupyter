"""
Pydantic V2 Models for MCP Tool Input Validation

Phase 3.1: All tool arguments use validated Pydantic models to prevent:
- Injection attacks (shell metacharacters, path traversal)
- Memory exhaustion (field length limits)
- Type confusion (strict type enforcement)
- Invalid parameters (range constraints)
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from pathlib import Path
from typing import Optional, Dict
import re


class SecureBaseModel(BaseModel):
    """Base class with extra='forbid' to reject unknown fields."""

    model_config = ConfigDict(extra="forbid")


# ============================================================================
# KERNEL MANAGEMENT TOOLS
# ============================================================================


class StartKernelArgs(SecureBaseModel):
    """Arguments for start_kernel tool."""

    notebook_path: str = Field(..., description="Absolute path to the notebook")
    venv_path: Optional[str] = Field(
        default="", description="Path to Python virtual environment"
    )

    timeout: int = Field(
        default=300, ge=10, le=3600, description="Kernel startup timeout in seconds"
    )
    agent_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional agent identifier to isolate CWD",
    )

    @field_validator("notebook_path")
    @classmethod
    def validate_notebook_path(cls, v):
        """Prevent path traversal attacks."""
        if not v:
            raise ValueError("Notebook path cannot be empty")
        p = Path(v)
        if ".." in p.parts:
            raise ValueError("Path traversal detected (..)")
        if not str(p).endswith(".ipynb"):
            raise ValueError("Notebook must have .ipynb extension")
        return str(p)


class StopKernelArgs(SecureBaseModel):
    """Arguments for stop_kernel tool."""

    notebook_path: str = Field(
        ..., description="Path to notebook whose kernel should be stopped"
    )

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        if ".." in str(v):
            raise ValueError("Path traversal detected")
        return v


class InterruptKernelArgs(SecureBaseModel):
    """Arguments for interrupt_kernel tool."""

    notebook_path: str = Field(
        ..., description="Path to notebook whose kernel should be interrupted"
    )

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        if ".." in str(v):
            raise ValueError("Path traversal detected")
        return v


class RestartKernelArgs(SecureBaseModel):
    """Arguments for restart_kernel tool."""

    notebook_path: str = Field(
        ..., description="Path to notebook whose kernel should be restarted"
    )

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        if ".." in str(v):
            raise ValueError("Path traversal detected")
        return v


class GetKernelInfoArgs(SecureBaseModel):
    """Arguments for get_kernel_info tool."""

    notebook_path: str = Field(..., description="Path to notebook")

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


# ============================================================================
# CELL EXECUTION TOOLS
# ============================================================================


class RunCellArgs(SecureBaseModel):
    """Arguments for run_cell tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    index: int = Field(..., ge=0, description="Cell index (0-based)")
    code_override: Optional[str] = Field(
        None, max_length=100_000, description="Override cell code (max 100KB)"
    )
    task_id_override: Optional[str] = Field(
        None, max_length=100, description="Client-generated execution ID"
    )
    force: bool = Field(
        default=False, description="Bypass sync checks and run immediately (dangerous)"
    )

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        if ".." in str(v):
            raise ValueError("Path traversal detected")
        return v


class RunAllCellsArgs(SecureBaseModel):
    """Arguments for run_all_cells tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    force: bool = Field(
        default=False,
        description="Force run even if cell is tagged as frozen/expensive",
    )

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        if ".." in str(v):
            raise ValueError("Path traversal detected")
        return v


class CancelExecutionArgs(SecureBaseModel):
    """Arguments for cancel_execution tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    task_id: str = Field(..., max_length=100, description="Execution task ID to cancel")

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


# ============================================================================
# PACKAGE MANAGEMENT TOOLS
# ============================================================================


class InstallPackageArgs(SecureBaseModel):
    """Arguments for install_package tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    package: str = Field(
        ..., max_length=500, description="Package name or pip specifier"
    )

    @field_validator("package")
    @classmethod
    def validate_package(cls, v):
        """Prevent shell injection via package names."""
        if not v or not v.strip():
            raise ValueError("Package name cannot be empty")

        # Allow only safe characters for pip package specs
        # Valid: package-name, package[extra], package==1.0.0, package>=1.0
        if any(c in v for c in [";", "|", "&", "`", "$", "\n", "\r", "\\", '"', "'"]):
            raise ValueError("Shell metacharacters not allowed in package name")

        # Prevent command injection via newlines or subshells
        if any(word in v.lower() for word in ["&&", "||", "$(", "`"]):
            raise ValueError("Command chaining not allowed in package name")

        if len(v) > 500:
            raise ValueError("Package specifier too long (max 500 chars)")

        return v.strip()

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


class ListKernelPackagesArgs(SecureBaseModel):
    """Arguments for list_kernel_packages tool."""

    notebook_path: str = Field(..., description="Path to notebook")

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


# ============================================================================
# VARIABLE INSPECTION TOOLS
# ============================================================================


class GetVariableInfoArgs(SecureBaseModel):
    """Arguments for get_variable_info tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    var_name: str = Field(..., max_length=200, description="Variable name to inspect")

    @field_validator("var_name")
    @classmethod
    def validate_var_name(cls, v):
        """Validate Python identifier."""
        if not v:
            raise ValueError("Variable name cannot be empty")
        # Python identifier pattern
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", v):
            raise ValueError("Invalid Python identifier")
        return v

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


class ListVariablesArgs(SecureBaseModel):
    """Arguments for list_variables tool."""

    notebook_path: str = Field(..., description="Path to notebook")

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


class InspectVariableArgs(SecureBaseModel):
    """Arguments for inspect_variable tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    variable_name: str = Field(
        ..., max_length=200, description="Variable name to inspect"
    )

    @field_validator("variable_name")
    @classmethod
    def validate_var_name(cls, v):
        """Validate Python identifier."""
        if not v:
            raise ValueError("Variable name cannot be empty")
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", v):
            raise ValueError("Invalid Python identifier")
        return v

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


class GetVariableManifestArgs(SecureBaseModel):
    """Arguments for get_variable_manifest tool."""

    notebook_path: str = Field(..., description="Path to notebook")

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


# ============================================================================
# FILESYSTEM / WORKING DIRECTORY TOOLS
# ============================================================================


class CheckWorkingDirectoryArgs(SecureBaseModel):
    """Arguments for check_working_directory tool."""

    notebook_path: str = Field(..., description="Path to notebook")

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


class SetWorkingDirectoryArgs(SecureBaseModel):
    """Arguments for set_working_directory tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    path: str = Field(..., max_length=4096, description="New working directory path")

    @field_validator("path")
    @classmethod
    def validate_path_arg(cls, v):
        """Prevent path traversal and validate path."""
        if not v:
            raise ValueError("Path cannot be empty")
        # Allow absolute paths and relative paths, but flag suspicious patterns
        if any(
            dangerous in v for dangerous in ["../", "..\\", ";", "|", "&", "`", "$"]
        ):
            raise ValueError("Suspicious characters in path")
        if len(v) > 4096:
            raise ValueError("Path too long (max 4096 chars)")
        return v

    @field_validator("notebook_path")
    @classmethod
    def validate_notebook_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


# ============================================================================
# SYNC / STATE MANAGEMENT TOOLS
# ============================================================================


class DetectSyncNeededArgs(SecureBaseModel):
    """Arguments for detect_sync_needed tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    buffer_hashes: Optional[Dict[int, str]] = Field(
        default=None, description="Client-side cell hashes"
    )

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


class SyncStateFromDiskArgs(SecureBaseModel):
    """Arguments for sync_state_from_disk tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    strategy: str = Field(
        default="minimal_append",
        pattern="^(minimal_append|smart|incremental|full|force)$",
        description="Sync strategy",
    )

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


# ============================================================================
# INPUT/OUTPUT TOOLS
# ============================================================================


class SubmitInputArgs(SecureBaseModel):
    """Arguments for submit_input tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    text: str = Field(..., max_length=10_000, description="User input text (max 10KB)")

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


# ============================================================================
# DATABASE QUERY TOOLS
# ============================================================================


# ============================================================================
# CHECKPOINT TOOLS (DEPRECATED - included for compatibility)
# ============================================================================


class SaveCheckpointArgs(SecureBaseModel):
    """Arguments for save_checkpoint tool (deprecated)."""

    notebook_path: str = Field(..., description="Path to notebook")
    checkpoint_name: str = Field(
        default="auto", max_length=100, description="Checkpoint name"
    )

    @field_validator("checkpoint_name")
    @classmethod
    def validate_checkpoint_name(cls, v):
        """Validate checkpoint name (alphanumeric + underscore/dash)."""
        if not v:
            raise ValueError("Checkpoint name cannot be empty")
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "Checkpoint name must be alphanumeric with underscores/dashes"
            )
        return v

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


class LoadCheckpointArgs(SecureBaseModel):
    """Arguments for load_checkpoint tool (deprecated)."""

    notebook_path: str = Field(..., description="Path to notebook")
    checkpoint_name: str = Field(
        default="auto", max_length=100, description="Checkpoint name"
    )

    @field_validator("checkpoint_name")
    @classmethod
    def validate_checkpoint_name(cls, v):
        """Validate checkpoint name."""
        if not v:
            raise ValueError("Checkpoint name cannot be empty")
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "Checkpoint name must be alphanumeric with underscores/dashes"
            )
        return v

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v


# ============================================================================
# ENVIRONMENT SWITCHING TOOLS
# ============================================================================


class SwitchKernelEnvironmentArgs(SecureBaseModel):
    """Arguments for switch_kernel_environment tool."""

    notebook_path: str = Field(..., description="Path to notebook")
    venv_path: str = Field(
        ..., max_length=4096, description="Path to virtual environment"
    )

    @field_validator("venv_path")
    @classmethod
    def validate_venv_path(cls, v):
        """Validate venv path."""
        if not v:
            raise ValueError("Virtual environment path cannot be empty")
        if any(char in v for char in [";", "|", "&", "`", "$", "\n", "\r"]):
            raise ValueError("Shell metacharacters not allowed in venv path")
        if len(v) > 4096:
            raise ValueError("Path too long (max 4096 chars)")
        return v

    @field_validator("notebook_path")
    @classmethod
    def validate_path(cls, v):
        if not v:
            raise ValueError("Notebook path cannot be empty")
        return v



class GetTrainingTemplateArgs(SecureBaseModel):
    """Arguments for get_training_template tool."""

    library: str = Field(..., description="ML library (pytorch, tensorflow)")

    @field_validator("library")
    @classmethod
    def validate_library(cls, v):
        """Validate library name."""
        valid = ["pytorch", "tensorflow"]
        if v.lower() not in valid:
            raise ValueError(f"Library must be one of: {valid}")
        return v
