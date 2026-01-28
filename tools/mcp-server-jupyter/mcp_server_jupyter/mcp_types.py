"""
Local MCP type definitions to avoid dependency on the MCP SDK.
This server is a standalone implementation and doesn't need the client SDK.
"""
from typing import Literal
from pydantic import BaseModel


class TextContent(BaseModel):
    """Text content for MCP messages."""
    type: Literal["text"] = "text"
    text: str


class PromptMessage(BaseModel):
    """Prompt message for MCP."""
    role: Literal["user", "assistant"]
    content: TextContent
