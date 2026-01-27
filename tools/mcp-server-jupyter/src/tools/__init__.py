"""
MCP Tools Package - Modular tool implementations for MCP Jupyter Server.

This package contains the refactored tools from main.py, organized by domain:
- kernel_tools: Kernel lifecycle management (start, stop, restart, interrupt)
- cell_tools: Cell manipulation (append, insert, delete, move, copy, merge, split)
- notebook_tools: Notebook operations (create, validate, metadata, outline)
- execution_tools: Code execution (run_cell, run_all, cancel, get_status)
- variable_tools: Variable inspection (list, inspect, manifest)
- environment_tools: Environment management (list envs, switch, create venv)
- asset_tools: Asset management (read, get content, prune, summary)
- proposal_tools: Edit proposal workflow
- data_tools: SQL queries on DataFrames, package installation
- server_tools: Server status, health, version
- diagnostic_tools: Enterprise support (export_diagnostic_bundle)
- prompts_tools: Prompt personas (jupyter_expert, autonomous_researcher, auto_analyst)
"""

from src.tools.kernel_tools import register_kernel_tools
from src.tools.cell_tools import register_cell_tools
from src.tools.notebook_tools import register_notebook_tools
from src.tools.execution_tools import register_execution_tools
from src.tools.variable_tools import register_variable_tools
from src.tools.environment_tools import register_environment_tools
from src.tools.interaction_tools import register_interaction_tools
from src.tools.asset_tools import register_asset_tools
from src.tools.proposal_tools import register_proposal_tools
from src.tools.server_tools import register_server_tools
from src.tools.data_tools import register_data_tools
from src.tools.diagnostic_tools import register_diagnostic_tools
from src.tools.prompts_tools import register_prompts
from src.tools.filesystem_tools import register_filesystem_tools


def register_all_tools(mcp, session_manager, connection_manager):
    """Register all tool modules with the MCP server."""
    register_server_tools(mcp, session_manager, connection_manager)
    register_kernel_tools(mcp, session_manager)
    register_cell_tools(mcp, session_manager)
    register_notebook_tools(mcp)
    register_execution_tools(mcp, session_manager)
    register_variable_tools(mcp, session_manager)
    register_environment_tools(mcp, session_manager)
    register_interaction_tools(mcp, session_manager)
    register_asset_tools(mcp)
    register_proposal_tools(mcp)
    register_data_tools(mcp, session_manager)
    register_diagnostic_tools(mcp, session_manager)
    register_prompts(mcp)
    register_filesystem_tools(mcp)
