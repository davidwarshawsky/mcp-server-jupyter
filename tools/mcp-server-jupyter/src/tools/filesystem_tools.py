import os
import base64
from pathlib import Path
from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP
from src.utils import ToolResult


class UploadFileRequest(BaseModel):
    target_path: str = Field(
        ...,
        description="Path where the file should be saved (relative to current working directory)",
    )
    base64_content: str = Field(..., description="Base64 encoded content of the file")


class DownloadFileRequest(BaseModel):
    source_path: str = Field(..., description="Path of the file to download")


def _validate_path(path_str: str) -> Path:
    """
    Validate that path is safe (doesn't traverse outside allowed areas).
    Encodes security policy:
    1. Must be relative to CWD or explicit allowed root.
    2. No .. traversal escaping limits.
    """
    # Simple security check: resolve path and ensure it's within CWD (or allowed root)

    cwd = Path.cwd().resolve()
    target = Path(path_str).resolve()

    # Allow CWD and /tmp (common for temporary operations)
    if target.is_relative_to(cwd):
        return target

    if target.is_relative_to(Path("/tmp")):
        return target

    # Check MCP_ALLOWED_ROOT if set
    allowed_root = os.environ.get("MCP_ALLOWED_ROOT")
    if allowed_root:
        allowed = Path(allowed_root).resolve()
        if target.is_relative_to(allowed):
            return target

    raise ValueError(
        f"Access denied: Path {path_str} is outside allowed directories ({cwd})"
    )


def register_filesystem_tools(mcp: FastMCP):
    """Register filesystem upload/download tools."""

    @mcp.tool()
    def upload_file(target_path: str, base64_content: str) -> str:
        """
        Upload a file to the remote environment.
        Useful when 'File Not Found' errors occur because data is on the client but not server.
        """
        try:
            path = _validate_path(target_path)

            # Decode content
            try:
                content = base64.b64decode(base64_content)
            except Exception:
                return ToolResult(
                    success=False, data="", error_msg="Invalid base64 content"
                ).to_json()

            # Create parent directories
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            with open(path, "wb") as f:
                f.write(content)

            return ToolResult(
                success=True,
                data=f"Successfully uploaded {len(content)} bytes to {path}",
            ).to_json()

        except Exception as e:
            return ToolResult(success=False, data="", error_msg=str(e)).to_json()

    @mcp.tool()
    def download_file(source_path: str) -> str:
        """
        Download a file from the remote environment.
        Returns the file content as base64 string.
        """
        try:
            path = _validate_path(source_path)

            if not path.exists():
                return ToolResult(
                    success=False, data="", error_msg=f"File not found: {source_path}"
                ).to_json()

            if not path.is_file():
                return ToolResult(
                    success=False, data="", error_msg=f"Not a file: {source_path}"
                ).to_json()

            # Read file
            with open(path, "rb") as f:
                content = f.read()

            encoded = base64.b64encode(content).decode("utf-8")

            return ToolResult(
                success=True,
                data={
                    "path": str(path),
                    "size": len(content),
                    "base64_content": encoded,
                },
            ).to_json()

        except Exception as e:
            return ToolResult(success=False, data="", error_msg=str(e)).to_json()
