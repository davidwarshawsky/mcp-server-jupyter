"""
Prompt Tools - Consumer-ready personas for Claude Desktop.

Provides system prompts that turn Claude into specialized Data Science personas:
- jupyter_expert: Safe, state-aware Data Science co-pilot
- autonomous_researcher: Self-directed research agent
- auto_analyst: Automated data analysis assistant
"""

from pathlib import Path
import mcp.types as types


def _read_prompt(filename: str) -> str:
    """Helper to read prompt files from the package."""
    try:
        # Locate the prompts directory relative to this file (src/tools/prompts_tools.py)
        current_dir = Path(__file__).parent.parent  # Go up to src/
        prompt_path = current_dir / "prompts" / filename

        if not prompt_path.exists():
            return f"Error: Prompt file '{filename}' not found at {prompt_path}"

        return prompt_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading prompt: {str(e)}"


def register_prompts(mcp):
    """Register prompt personas with the MCP server."""

    @mcp.prompt()
    def jupyter_expert() -> list[types.PromptMessage]:
        """
        Returns the System Prompt for the Jupyter Expert persona.
        Use this to turn Claude into a safe, state-aware Data Science co-pilot.

        Activates with: /prompt jupyter-expert

        Persona traits:
        - Always checks sync status before execution
        - Uses inspect_variable for large DataFrames
        - Searches notebooks before reading full content
        - Follows Hub and Spoke architecture
        """
        content = _read_prompt("jupyter_expert.md")
        return [
            types.PromptMessage(
                role="user", content=types.TextContent(type="text", text=content)
            )
        ]

    @mcp.prompt()
    def autonomous_researcher() -> list[types.PromptMessage]:
        """
        Returns the System Prompt for the Autonomous Researcher persona.
        Self-directed agent for complex research tasks.

        Activates with: /prompt autonomous-researcher

        Persona traits:
        - Plans multi-step analysis autonomously
        - Creates checkpoints before risky operations
        - Documents findings in markdown cells
        - Uses Git integration for version control
        """
        content = _read_prompt("autonomous_researcher.md")
        return [
            types.PromptMessage(
                role="user", content=types.TextContent(type="text", text=content)
            )
        ]

    @mcp.prompt()
    def auto_analyst() -> list[types.PromptMessage]:
        """
        Returns the System Prompt for the Auto Analyst persona.
        Automated data analysis with visualization focus.

        Activates with: /prompt auto-analyst

        Persona traits:
        - Generates comprehensive EDA reports
        - Creates visualizations for every insight
        - Suggests next analysis steps
        - Exports findings as clean notebooks
        """
        content = _read_prompt("auto_analyst.md")
        return [
            types.PromptMessage(
                role="user", content=types.TextContent(type="text", text=content)
            )
        ]
