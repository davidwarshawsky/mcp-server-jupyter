"""
Diagnostic Tools - Enterprise support and troubleshooting tools.

Includes: export_diagnostic_bundle
"""

import os
import sys
import json
import datetime
import zipfile
import tempfile
import subprocess
from pathlib import Path
from src.observability import get_logger
from src.config import load_and_validate_settings

logger = get_logger(__name__)
settings = load_and_validate_settings()


def register_diagnostic_tools(mcp, session_manager):
    """Register diagnostic tools with the MCP server."""
    
    @mcp.tool()
    def export_diagnostic_bundle():
        """
        [ENTERPRISE SUPPORT] Export a diagnostic bundle for troubleshooting.
        
        Creates a ZIP file containing:
        - .mcp/ directory (session files, checkpoints)
        - Latest server.log (error diagnostics)
        - System info (Python version, packages, OS)
        
        **Use When**: "Something broke. Let me send you the diagnostic bundle."
        
        **What Support Gets**:
        - Complete session state
        - Full error trace
        - Environment details
        
        Returns:
            JSON with path to ZIP file and size
            
        Example:
            bundle = export_diagnostic_bundle()
            # Returns: {"path": "/tmp/mcp-diag-2025-01-17.zip", "size_mb": 2.5}
            # Share this file with IT/Support for 30-second diagnosis
        """
        try:
            # Create temporary ZIP
            fd, zip_path = tempfile.mkstemp(suffix='.zip', prefix='mcp-diag-')
            os.close(fd)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 1. Include .mcp directory (sessions, checkpoints)
                mcp_dir = settings.get_data_dir()
                if mcp_dir.exists():
                    for file in mcp_dir.rglob('*'):
                        if file.is_file():
                            zf.write(file, arcname=f".mcp/{file.relative_to(mcp_dir)}")
                
                # 2. Include latest logs
                log_files = list(Path.cwd().glob("*.log"))
                for log_file in log_files[-5:]:  # Last 5 log files
                    if log_file.is_file():
                        zf.write(log_file, arcname=f"logs/{log_file.name}")
                
                # 3. Include system info
                sysinfo = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "python_version": sys.version,
                    "platform": sys.platform,
                    "active_sessions": len(session_manager.sessions),
                    "installed_packages": {}
                }
                
                # Capture pip list
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "list", "--format", "json"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        sysinfo["installed_packages"] = json.loads(result.stdout)
                except Exception:
                    pass
                
                # Write sysinfo.json
                zf.writestr("sysinfo.json", json.dumps(sysinfo, indent=2))
            
            # Get file size
            size_mb = Path(zip_path).stat().st_size / (1024 * 1024)
            
            return json.dumps({
                "status": "success",
                "path": zip_path,
                "size_mb": round(size_mb, 2),
                "message": "Diagnostic bundle created. Share this with IT/Support for quick diagnosis.",
                "instructions": "Email this file to data-tools@yourorg.com with subject 'MCP Jupyter Issue Report'"
            }, indent=2)
            
        except Exception as e:
            logger.error(f"[DIAGNOSTIC] Failed to create bundle: {e}")
            return json.dumps({
                "status": "error",
                "error": str(e)
            }, indent=2)
