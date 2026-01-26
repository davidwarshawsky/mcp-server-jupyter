"""
Kernel Tools - Kernel lifecycle management tools.

Includes: start_kernel, stop_kernel, list_kernels, interrupt_kernel, 
restart_kernel, check_working_directory, set_working_directory,
list_kernel_packages, list_available_environments, switch_kernel_environment
"""

import json
from src.audit_log import audit_tool
from typing import Optional
from src.observability import get_logger, get_tracer
from src.validation import validated_tool
from src.models import (
    StartKernelArgs,
    StopKernelArgs,
    InterruptKernelArgs,
    RestartKernelArgs,
    CheckWorkingDirectoryArgs,
    SetWorkingDirectoryArgs,
    ListKernelPackagesArgs,
    SwitchKernelEnvironmentArgs,
)

logger = get_logger(__name__)
tracer = get_tracer(__name__)


def register_kernel_tools(mcp, session_manager):
    """Register kernel lifecycle tools with the MCP server."""

    @mcp.tool()
    @audit_tool
    @validated_tool(StartKernelArgs)
    async def start_kernel(
        notebook_path: str,
        venv_path: str = "",
        docker_image: str = "",
        timeout: int = 300,
        agent_id: Optional[str] = None,
    ):
        """
        Boot a background process.
        Windows Logic: Looks for venv_path/Scripts/python.exe.
        Ubuntu Logic: Looks for venv_path/bin/python.
        Docker Logic: If docker_image is set, runs kernel securely in container.
        Timeout: Seconds before killing long-running cells (default: 300).
        Output: "Kernel started (PID: 1234). Ready for execution."
        """
        with tracer.start_as_current_span("tool.start_kernel") as span:
            span.set_attribute("notebook_path", notebook_path)
            span.set_attribute("docker_image", docker_image)
            # Capture the active session for notifications
            try:
                ctx = mcp.get_context()
                if ctx and ctx.request_context:
                    session_manager.register_session(ctx.request_context.session)
            except:
                # Ignore if context not available (e.g. testing)
                pass

            # Security Check
            if not docker_image:
                logger.warning(
                    f"Unsandboxed execution requested for {notebook_path}. All code runs with user privileges."
                )

            return await session_manager.start_kernel(
                notebook_path,
                venv_path if venv_path else None,
                docker_image if docker_image else None,
                timeout,
                agent_id=agent_id,
            )

    @mcp.tool()
    @audit_tool
    @validated_tool(StopKernelArgs)
    async def stop_kernel(notebook_path: str):
        """
        Kill the process to free RAM and clean up assets.
        """
        with tracer.start_as_current_span("tool.stop_kernel") as span:
            span.set_attribute("notebook_path", notebook_path)
            # 1. Prune assets before stopping
            from src.asset_manager import prune_unused_assets

            try:
                # Run cleanup. This ensures that if I delete a cell and close the notebook,
                # the orphaned image is deleted.
                prune_unused_assets(notebook_path, dry_run=False)
            except Exception as e:
                logger.warning(f"Asset cleanup failed: {e}")

            return await session_manager.stop_kernel(notebook_path)

    @mcp.tool()
    @audit_tool
    def list_kernels():
        """
        List all active kernel sessions.
        Returns: JSON with notebook paths and kernel status.
        """
        result = []
        for nb_path, session in session_manager.sessions.items():
            pid = "unknown"
            if hasattr(session.get("km"), "kernel") and session["km"].kernel:
                pid = getattr(session["km"].kernel, "pid", "unknown")

            result.append(
                {
                    "notebook_path": nb_path,
                    "pid": pid,
                    "cwd": session.get("cwd", "unknown"),
                    "execution_count": session.get("execution_counter", 0),
                    "queue_size": (
                        session["execution_queue"].qsize()
                        if "execution_queue" in session
                        else 0
                    ),
                    "stop_on_error": session.get("stop_on_error", False),
                }
            )

        return json.dumps(result, indent=2)

    @mcp.tool()
    @audit_tool
    @validated_tool(InterruptKernelArgs)
    async def interrupt_kernel(notebook_path: str):
        """Stops the currently running cell immediately."""
        return await session_manager.interrupt_kernel(notebook_path)

    @mcp.tool()
    @audit_tool
    @validated_tool(RestartKernelArgs)
    async def restart_kernel(notebook_path: str):
        """Restarts the kernel, clearing all variables but keeping outputs."""
        return await session_manager.restart_kernel(notebook_path)

    @mcp.tool()
    @audit_tool
    @validated_tool(CheckWorkingDirectoryArgs)
    async def check_working_directory(notebook_path: str):
        """Checks the current working directory (CWD) of the active kernel."""
        code = "import os; print(os.getcwd())"
        return await session_manager.run_simple_code(notebook_path, code)

    @mcp.tool()
    @audit_tool
    @validated_tool(SetWorkingDirectoryArgs)
    async def set_working_directory(notebook_path: str, path: str):
        """Changes the CWD of the kernel."""
        # Escape backslashes for Windows
        safe_path = path.replace("\\", "/")
        code = f"import os; os.chdir('{safe_path}'); print(os.getcwd())"
        result = await session_manager.run_simple_code(notebook_path, code)
        if "Error" in result:
            return result
        return f"Working directory changed to: {result}"

    @mcp.tool()
    @audit_tool
    @validated_tool(ListKernelPackagesArgs)
    async def list_kernel_packages(notebook_path: str):
        """Lists packages installed in the active kernel's environment."""
        # We run this inside python to avoid OS shell syntax differences
        code = """
import pkg_resources
installed = sorted([(d.project_name, d.version) for d in pkg_resources.working_set])
for p, v in installed:
    print(f"{p}=={v}")
"""
        return await session_manager.run_simple_code(notebook_path, code)

    @mcp.tool()
    @audit_tool
    def list_available_environments():
        """Scans the system for Python environments (venvs, conda, etc)."""
        envs = session_manager.list_environments()
        return json.dumps(envs, indent=2)

    @mcp.tool()
    @audit_tool
    @validated_tool(SwitchKernelEnvironmentArgs)
    async def switch_kernel_environment(notebook_path: str, venv_path: str):
        """
        Stops the current kernel and restarts it using the specified environment path.
        path: The absolute path to the environment root (not the bin/python executable).
        """
        # 1. Stop
        await session_manager.stop_kernel(notebook_path)

        # 2. Start with new env
        result = await session_manager.start_kernel(notebook_path, venv_path)
        return f"Switched Environment. {result}"
