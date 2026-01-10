import os
import sys
import asyncio
import uuid
import json
import logging
import nbformat
import datetime
import subprocess
try:
    import dill
except ImportError:
    dill = None
from pathlib import Path
from typing import Dict, Any, Optional
from jupyter_client.manager import AsyncKernelManager
from src import notebook, utils
from src.cell_id_manager import get_cell_id_at_index

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_activated_env_vars(venv_path: str, python_exe: str) -> Optional[Dict[str, str]]:
    """
    Get fully activated environment variables for conda/venv environments.
    
    Critical for conda environments where packages like PyTorch/TensorFlow need
    LD_LIBRARY_PATH, CUDA_HOME, and other env vars set by activation scripts.
    
    Args:
        venv_path: Path to the environment directory
        python_exe: Python executable within that environment
    
    Returns:
        Dict of environment variables after activation, or None if not conda
    """
    venv_path_obj = Path(venv_path).resolve()
    
    # Detect if this is a conda environment
    is_conda = (venv_path_obj / "conda-meta").exists()
    
    if not is_conda:
        # For regular venv, just updating Python path is usually sufficient
        # Return current environment with updated PATH
        env = os.environ.copy()
        bin_dir = str(Path(python_exe).parent)
        if bin_dir not in env.get('PATH', ''):
            env['PATH'] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        return env
    
    # For conda, we implement "Direct Binary Resolution" (Fast Mode)
    # Instead of slow 'conda run', we manually construct the environment.
    # This saves ~1-3 seconds of latency per kernel start.
    
    env = os.environ.copy()
    bin_dir = str(Path(python_exe).parent)
    
    # 1. Essential Conda Vars
    env['CONDA_PREFIX'] = str(venv_path_obj)
    env['CONDA_DEFAULT_ENV'] = venv_path_obj.name
    
    # 2. Update PATH (Priority to environment bin)
    # On Windows: env/Scripts; env/Library/bin; env/Library/usr/bin; env/Library/mingw-w64/bin; env
    # On Unix: env/bin
    if os.name == 'nt':
        scripts = venv_path_obj / "Scripts"
        lib_bin = venv_path_obj / "Library" / "bin"
        lib_usr_bin = venv_path_obj / "Library" / "usr" / "bin"
        
        paths_to_add = [str(p) for p in [scripts, lib_bin, lib_usr_bin, venv_path_obj] if p.exists()]
        env['PATH'] = os.pathsep.join(paths_to_add) + os.pathsep + env.get('PATH', '')
    else:
        # Unix
        # Note: Some conda envs might have separate library paths, but bin/ usually covers it for execution
        env['PATH'] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        
    logger.info(f"Directly resolved conda env: {venv_path} (Fast Start)")
    return env

class SessionManager:
    def __init__(self):
        # Maps notebook_path (str) -> {
        #   'km': KernelManager, 
        #   'kc': Client, 
        #   'cwd': str,
        #   'listener_task': asyncio.Task,
        #   'executions': Dict[str (msg_id), Dict],
        #   'queued_executions': Dict[str (exec_id), Dict],  # Track queued before processing
        #   'execution_queue': asyncio.Queue,
        #   'queue_processor_task': asyncio.Task,
        #   'execution_counter': int,
        #   'stop_on_error': bool
        # }
        self.sessions = {}
        # Global timeout for cell executions (in seconds)
        self.execution_timeout = 300  # 5 minutes
        
        # Reference to MCP server for notifications
        self.mcp_server = None
        self.server_session = None
        
        # Session persistence directory
        self.persistence_dir = Path.home() / ".mcp-jupyter" / "sessions"
        self.persistence_dir.mkdir(parents=True, exist_ok=True)
        
    def set_mcp_server(self, mcp_server):
        """Set the MCP server instance to enable notifications."""
        self.mcp_server = mcp_server

    def register_session(self, session):
        """Register the active ServerSession for sending notifications."""
        self.server_session = session

    async def _send_notification(self, method: str, params: Any):
        """Helper to send notifications via available channel."""
        # Wrap custom notification to satisfy MCP SDK interface
        class CustomNotification:
            def __init__(self, method, params):
                self.method = method
                self.params = params
            def model_dump(self, **kwargs):
                return {"method": self.method, "params": self.params}

        notification = CustomNotification(method, params)

        if self.server_session:
            await self.server_session.send_notification(notification)
        elif self.mcp_server and hasattr(self.mcp_server, "send_notification"):
            await self.mcp_server.send_notification(notification)

    
    def _persist_session_info(self, nb_path: str, connection_file: str, pid: Any, env_info: Dict):
        """
        Save session info to disk to prevent zombie kernels after server restart.
        
        Stores:
        - Connection file path (for reconnecting to kernel)
        - Process ID (for checking if kernel still alive)
        - Environment info (for proper cleanup)
        """
        try:
            # Use notebook path hash as filename to handle special chars
            import hashlib
            path_hash = hashlib.md5(nb_path.encode()).hexdigest()
            session_file = self.persistence_dir / f"session_{path_hash}.json"
            
            session_data = {
                "notebook_path": nb_path,
                "connection_file": connection_file,
                "pid": pid if isinstance(pid, int) else None,
                "env_info": env_info,
                "created_at": datetime.datetime.now().isoformat()
            }
            
            with open(session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            
            logger.info(f"Persisted session info for {nb_path} (PID: {pid})")
        except Exception as e:
            logger.warning(f"Failed to persist session info: {e}")
    
    def _remove_persisted_session(self, nb_path: str):
        """Remove persisted session info when kernel is shut down."""
        try:
            import hashlib
            path_hash = hashlib.md5(nb_path.encode()).hexdigest()
            session_file = self.persistence_dir / f"session_{path_hash}.json"
            
            if session_file.exists():
                session_file.unlink()
                logger.info(f"Removed persisted session for {nb_path}")
        except Exception as e:
            logger.warning(f"Failed to remove persisted session: {e}")
    
    async def restore_persisted_sessions(self):
        """
        Attempt to restore sessions from disk on server startup.
        
        Checks if kernel PIDs are still alive and reconnects if possible.
        Cleans up stale session files for dead kernels.
        """
        restored_count = 0
        cleaned_count = 0
        
        for session_file in self.persistence_dir.glob("session_*.json"):
            try:
                with open(session_file, 'r') as f:
                    session_data = json.load(f)
                
                nb_path = session_data['notebook_path']
                pid = session_data['pid']
                connection_file = session_data['connection_file']
                
                # Check if kernel process is still alive
                try:
                    # Lazy import to avoid startup crashes
                    import psutil
                    if psutil.pid_exists(pid) and Path(connection_file).exists():
                        # Try to reconnect to existing kernel
                        logger.info(f"Attempting to restore session for {nb_path} (PID: {pid})")
                        
                        try:
                            # Create kernel manager from existing connection file
                            km = AsyncKernelManager(connection_file=connection_file)
                            km.load_connection_file()
                            
                            # Create client and connect
                            kc = km.client()
                            kc.start_channels()
                            
                            # Test if kernel is responsive
                            await asyncio.wait_for(kc.wait_for_ready(timeout=10), timeout=15)
                            
                            # Get notebook directory for CWD
                            notebook_dir = str(Path(nb_path).parent.resolve())
                            
                            # Restore session structure
                            abs_path = str(Path(nb_path).resolve())
                            session_dict = {
                                'km': km,
                                'kc': kc,
                                'cwd': notebook_dir,
                                'listener_task': None,
                                'executions': {},
                                'queued_executions': {},
                                'execution_queue': asyncio.Queue(),
                                'execution_counter': 0,
                                'stop_on_error': False,
                                'env_info': session_data.get('env_info', {
                                    'python_path': 'unknown',
                                    'env_name': 'unknown',
                                    'start_time': session_data.get('created_at', 'unknown')
                                })
                            }
                            
                            # Start background tasks
                            session_dict['listener_task'] = asyncio.create_task(
                                self._kernel_listener(abs_path, kc, session_dict['executions'])
                            )
                            session_dict['queue_processor_task'] = asyncio.create_task(
                                self._queue_processor(abs_path, session_dict)
                            )
                            
                            self.sessions[abs_path] = session_dict
                            restored_count += 1
                            logger.info(f"Successfully restored session for {nb_path}")
                            
                        except Exception as reconnect_error:
                            logger.warning(f"Failed to reconnect to kernel PID {pid}: {reconnect_error}")
                            # Clean up the stale session file
                            session_file.unlink()
                            cleaned_count += 1
                    else:
                        # Kernel is dead or connection file missing, clean up
                        if not psutil.pid_exists(pid):
                            logger.info(f"Kernel PID {pid} for {nb_path} is dead, cleaning up")
                        else:
                            logger.info(f"Connection file {connection_file} missing, cleaning up session")
                        session_file.unlink()
                        cleaned_count += 1
                except ImportError:
                    logger.warning("psutil not available, skipping session restoration")
                    break
                    
            except Exception as e:
                logger.warning(f"Failed to restore session from {session_file}: {e}")
                # Clean up corrupted session file
                try:
                    session_file.unlink()
                except:
                    pass
        
        if restored_count > 0:
            logger.info(f"Restored {restored_count} sessions from disk")
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} stale session files")

    def get_python_path(self, venv_path: Optional[str]) -> str:
        """Cross-platform venv resolver"""
        if not venv_path:
             return sys.executable
             
        root = Path(venv_path).resolve()
        
        # Windows Check
        if os.name == 'nt':
            candidate = root / "Scripts" / "python.exe"
            if candidate.exists(): return str(candidate)
            
        # Linux/Mac Check
        candidate = root / "bin" / "python"
        if candidate.exists(): return str(candidate)
        
        # Fallback
        return sys.executable

    async def start_kernel(self, nb_path: str, venv_path: Optional[str] = None, docker_image: Optional[str] = None):
        abs_path = str(Path(nb_path).resolve())
        # Determine the Notebook's directory to set as CWD
        notebook_dir = str(Path(nb_path).parent.resolve())

        if abs_path in self.sessions: 
            return f"Kernel already running for {abs_path}"
        
        km = AsyncKernelManager()
        
        if docker_image:
             # [PHASE 4: Docker Support]
             # Strategy: Use docker run to launch the kernel
             # We must mount:
             # 1. The workspace (so imports work)
             # 2. The connection file (so we can talk to it)
             
             # Locate workspace root (Simple heuristic: look for .git or go up logic)
             # For now, we mount the notebook directory. 
             # TODO: More robust root detection
             mount_source = notebook_dir
             mount_target = "/workspace"
             
             # Construct Docker Command
             # We use {connection_file} which Jupyter substitutes with the host path
             # We map Host Path -> Container Path (/kernel.json)
             # Then tell ipykernel to read /kernel.json
             
             cmd = [
                 'docker', 'run', 
                 '--rm',                     # Cleanup container on exit
                 '-i',                       # Interactive (keeps stdin open)
                 '-u', str(os.getuid()),     # Run as current user (avoid root file issues)
                 '-v', f'{mount_source}:{mount_target}',
                 '-v', '{connection_file}:/kernel.json',
                 '-w', mount_target,
                 docker_image,
                 'python', '-m', 'ipykernel_launcher', '-f', '/kernel.json'
             ]
             
             km.kernel_cmd = cmd
             logger.info(f"Configured Docker kernel: {cmd}")
             
             # We explicitly do NOT activate local envs if using Docker
             # Docker image is the environment
             kernel_env = {} 
        
        else:
            # 1. Handle Environment (Local)
            py_exe = sys.executable
        env_name = "system"
        kernel_env = os.environ.copy()  # Default: inherit current environment
        
        if venv_path:
            py_exe = self.get_python_path(venv_path)
            env_name = Path(venv_path).name
            # Better: if venv_path provided, ensure py_exe starts with it.
            if venv_path and not str(py_exe).lower().startswith(str(Path(venv_path).resolve()).lower()):
                 return f"Error: Could not find python executable in {venv_path}"

            # Get fully activated environment variables (critical for conda + PyTorch/TensorFlow)
            kernel_env = _get_activated_env_vars(venv_path, py_exe)
            if kernel_env:
                logger.info(f"Using activated environment for {env_name} with {len(kernel_env)} env vars")
            else:
                logger.warning(f"Failed to activate environment {venv_path}, using basic PATH update")
                # Fallback: just update PATH
                kernel_env = os.environ.copy()
                bin_dir = str(Path(py_exe).parent)
                kernel_env['PATH'] = f"{bin_dir}{os.pathsep}{kernel_env.get('PATH', '')}"

            # Force Jupyter to use our Venv Python
            km.kernel_cmd = [py_exe, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
        
        # 2. Start Kernel with Correct CWD and Environment
        await km.start_kernel(cwd=notebook_dir, env=kernel_env)
        
        kc = km.client()
        kc.start_channels()
        try:
            await kc.wait_for_ready(timeout=60)
        except Exception as e:
            if km.has_kernel:
                await km.shutdown_kernel()
            raise RuntimeError(f"Kernel failed to start: {str(e)}")
        
        # 3. Inject autoreload and visualization configuration immediately after kernel ready
        # Execute startup setup (fire-and-forget for reliability)
        startup_code = '''
%load_ext autoreload
%autoreload 2

import sys
import json
import traceback

# [STDIN BLOCKING] Prevent input() from hanging the kernel

# Override built-in input() to raise error immediately instead of waiting forever
def _mcp_blocked_input(prompt=''):
    raise RuntimeError(
        "input() is disabled in MCP-managed kernels. "
        "AI agents cannot provide interactive input. "
        "Use hardcoded values or environment variables instead."
    )

# Replace builtins
import builtins
builtins.input = _mcp_blocked_input
# Python 2 compatibility (though ipykernel requires Python 3)
builtins.raw_input = _mcp_blocked_input


# [SECURITY] Safe Inspection Helper
# Pre-compile inspection logic to avoid sending large code blocks
# Must be consistent with _mcp_inspect in session.py
INSPECT_HELPER_CODE = """
def _mcp_inspect(var_name):
    import builtins
    import sys
    
    # Safe lookup: Check locals then globals
    # Note: In ipykernel, user variables are in globals()
    ns = globals()
    if var_name not in ns:
        return f"Variable '{var_name}' not found."
    
    obj = ns[var_name]
    
    try:
        t_name = type(obj).__name__
        output = [f"### Type: {t_name}"]
        
        # Check for pandas/numpy without importing if not already imported
        is_pd_df = 'pandas' in sys.modules and isinstance(obj, sys.modules['pandas'].DataFrame)
        is_pd_series = 'pandas' in sys.modules and isinstance(obj, sys.modules['pandas'].Series)
        is_numpy = 'numpy' in sys.modules and hasattr(obj, 'shape') and hasattr(obj, 'dtype')
        
        # Safe Primitives
        if isinstance(obj, (int, float, bool, str, bytes, type(None))):
             output.append(f"- Value: {str(obj)[:500]}")

        elif is_pd_df:
            output.append(f"- Shape: {obj.shape}")
            output.append(f"- Columns: {list(obj.columns)}")
            output.append("\\n#### Head (3 rows):")
            # to_markdown requires tabulate, fallback to string if fails
            try:
                output.append(obj.head(3).to_markdown(index=False))
            except:
                output.append(str(obj.head(3)))
            
        elif is_pd_series:
            output.append(f"- Length: {len(obj)}")
            try:
                output.append(obj.head(3).to_markdown())
            except:
                output.append(str(obj.head(3)))
            
        elif is_numpy:
            output.append(f"- Shape: {obj.shape}")
            output.append(f"- Dtype: {obj.dtype}")
            
        elif isinstance(obj, (list, tuple, set)):
             output.append(f"- Length: {len(obj)}")
             output.append(f"- Sample: {str(list(obj)[:3])}")
             
        elif isinstance(obj, dict):
             output.append(f"- Keys ({len(obj)}): {list(obj.keys())[:5]}")
             
        elif hasattr(obj, '__dict__'):
             output.append(f"- Attributes: {list(obj.__dict__.keys())[:5]}")
             
        return "\\n".join(output)
            
    except Exception as e:
        return f"Error inspecting '{var_name}': {str(e)}"
"""

# [END SECURITY HELPER]

# [PHASE 3.3] Force static rendering for interactive visualization libraries
# This allows AI agents to "see" plots that would otherwise be JavaScript-based
import os
try:
    import matplotlib
    matplotlib.use('Agg')  # Headless backend for matplotlib
    get_ipython().run_line_magic('matplotlib', 'inline')
except ImportError:
    pass  # matplotlib not installed, skip

# [PHASE 4: Smart Error Recovery]
# Inject a custom exception handler to provide context-aware error reports
        
    get_ipython().set_custom_exc((Exception,), _mcp_handler)

except Exception as e:
    pass # Failed to register error handler

# Force Plotly to render as static PNG
# NOTE: Requires kaleido installed in kernel environment: pip install kaleido
try:

    import plotly
    try:
        import kaleido
        os.environ['PLOTLY_RENDERER'] = 'png'
    except ImportError:
        # Kaleido not installed - Plotly will fall back to HTML output
        # which will be sanitized to text by the asset extraction pipeline
        pass
except ImportError:
    pass  # plotly not installed, skip

# Force Bokeh to use static SVG backend
try:
    import bokeh
    os.environ['BOKEH_OUTPUT_BACKEND'] = 'svg'
except ImportError:
    pass  # bokeh not installed, skip
'''
        try:
            kc.execute(startup_code, silent=True)
            # Give it a moment to take effect
            await asyncio.sleep(0.5)
            logger.info("Autoreload and visualization config sent to kernel")
            
            # Add cwd to path
            path_code = "import sys, os\nif os.getcwd() not in sys.path: sys.path.append(os.getcwd())"
            kc.execute(path_code, silent=True)
            logger.info("Path setup sent to kernel")
            
        except Exception as e:
            logger.warning(f"Failed to inject startup code: {e}")
            
        # Create session dictionary structure
        execution_queue = asyncio.Queue()
        session_data = {
            'km': km,
            'kc': kc,
            'cwd': notebook_dir,
            'listener_task': None,
            'executions': {},
            'queued_executions': {},  # Track queued executions before processing
            'execution_queue': asyncio.Queue(),
            'execution_counter': 0,
            'stop_on_error': False,  # NEW: Default to False for backward compatibility
            'env_info': {  # NEW: Environment provenance tracking
                'python_path': py_exe,
                'env_name': env_name,
                'start_time': datetime.datetime.now().isoformat()
            }
        }
        
        # Start the background listener
        session_data['listener_task'] = asyncio.create_task(
            self._kernel_listener(abs_path, kc, session_data['executions'])
        )
        
        # Start the execution queue processor
        session_data['queue_processor_task'] = asyncio.create_task(
            self._queue_processor(abs_path, session_data)
        )
        
        self.sessions[abs_path] = session_data
        
        # Safely get PID and connection file
        pid = "unknown"
        connection_file = "unknown"
        if hasattr(km, 'kernel') and km.kernel:
            pid = getattr(km.kernel, 'pid', 'unknown')
        if hasattr(km, 'connection_file'):
            connection_file = km.connection_file
        
        # Persist session info to prevent zombie kernels after server restart
        if pid != "unknown" and connection_file != "unknown":
            self._persist_session_info(abs_path, connection_file, pid, session_data['env_info'])
                 
        return f"Kernel started (PID: {pid}). CWD set to: {notebook_dir}"

    async def _kernel_listener(self, nb_path: str, kc, executions: Dict):
        """
        Background loop that drains the IOPub channel for a specific kernel.
        It routes messages to the correct execution ID based on parent_header.
        """
        logger.info(f"Starting listener for {nb_path}")
        try:
            while True:
                # Retrieve message
                msg = await kc.get_iopub_msg()
                
                # Identify which execution this belongs to
                parent_id = msg['parent_header'].get('msg_id')
                if not parent_id or parent_id not in executions:
                    # Message might be from a previous run or system status
                    continue
                
                exec_data = executions[parent_id]
                msg_type = msg['msg_type']
                content = msg['content']

                # Update State
                if msg_type == 'status':
                    exec_data['kernel_state'] = content['execution_state']
                    if content['execution_state'] == 'idle':
                        if exec_data['status'] not in ['error', 'cancelled']:
                            exec_data['status'] = 'completed'
                        # Finalize: Save to disk
                        self._finalize_execution(nb_path, exec_data)
                        
                        # [PRIORITY 2] Emit Completion Notification
                        try:
                            await self._send_notification("notebook/status", {
                                "notebook_path": nb_path,
                                "exec_id": exec_data.get('id'),
                                "status": exec_data['status']
                            })
                        except Exception as e:
                            logger.warning(f"Failed to send status notification: {e}")

                elif msg_type == 'clear_output':
                    # [PHASE 3.1] Handle progress bars and dynamic updates (tqdm, etc.)
                    # Clear the outputs list to mimic Jupyter UI behavior
                    # This prevents file size explosion from thousands of progress updates
                    wait = content.get('wait', False)
                    if not wait:
                        # Immediate clear: reset outputs but keep streaming metadata
                        exec_data['outputs'] = []
                        # Note: output_count is NOT reset - agents track cumulative index
                        # This means the agent's stream will show gaps, but that's acceptable
                        # for progress bars (they only care about the final state)

                elif msg_type in ['stream', 'display_data', 'execute_result', 'error']:
                    # Convert to nbformat output
                    output = None
                    if msg_type == 'stream':
                        output = nbformat.v4.new_output('stream', name=content['name'], text=content['text'])
                    elif msg_type == 'display_data':
                        output = nbformat.v4.new_output('display_data', data=content['data'], metadata=content['metadata'])
                    elif msg_type == 'execute_result':
                        exec_data['execution_count'] = content.get('execution_count')
                        output = nbformat.v4.new_output('execute_result', data=content['data'], metadata=content['metadata'], execution_count=content.get('execution_count'))
                    elif msg_type == 'error':
                        exec_data['status'] = 'error'
                        output = nbformat.v4.new_output('error', ename=content['ename'], evalue=content['evalue'], traceback=content['traceback'])
                    
                    if output:
                        exec_data['outputs'].append(output)
                        # [PHASE 3.1] Update streaming metadata
                        exec_data['output_count'] = len(exec_data['outputs'])
                        exec_data['last_activity'] = asyncio.get_event_loop().time()
                        
                        # [PRIORITY 2] Emit MCP Notification (Event-Driven Architecture)
                        try:
                            await self._send_notification("notebook/output", {
                                "notebook_path": nb_path,
                                "exec_id": exec_data.get('id'),
                                "type": msg_type,
                                "content": content
                            })
                        except Exception as e:
                            # Don't crash the listener if notification fails
                            logger.warning(f"Failed to send MCP notification: {e}")

        except asyncio.CancelledError:
            logger.info(f"Listener cancelled for {nb_path}")
        except Exception as e:
            logger.error(f"Listener error for {nb_path}: {e}")

    async def _queue_processor(self, nb_path: str, session_data: Dict):
        """
        Background loop that processes execution requests from the queue.
        Ensures only one cell executes at a time per notebook.
        """
        logger.info(f"Starting queue processor for {nb_path}")
        try:
            while True:
                # Get next execution request from queue
                exec_request = await session_data['execution_queue'].get()
                
                # Check for shutdown signal
                if exec_request is None:
                    logger.info(f"Queue processor shutting down for {nb_path}")
                    break
                
                cell_index = exec_request['cell_index']
                code = exec_request['code']
                exec_id = exec_request['exec_id']
                
                # Remove from queued executions (now processing)
                if exec_id in session_data['queued_executions']:
                    del session_data['queued_executions'][exec_id]
                
                try:
                    # Increment execution counter
                    session_data['execution_counter'] += 1
                    expected_count = session_data['execution_counter']
                    
                    # Execute the cell
                    kc = session_data['kc']
                    msg_id = kc.execute(code)
                    
                    # Register execution with expected count
                    session_data['executions'][msg_id] = {
                        'id': exec_id,
                        'cell_index': cell_index,
                        'status': 'running',
                        'outputs': [],
                        'execution_count': expected_count,
                        'text_summary': "",
                        'kernel_state': 'busy',
                        'start_time': asyncio.get_event_loop().time(),
                        'output_count': 0,  # [PHASE 3.1] Track total output count for streaming
                        'last_activity': asyncio.get_event_loop().time()  # [PHASE 3.1] Last output timestamp
                    }
                    
                    # Wait for execution to complete with timeout
                    timeout_remaining = self.execution_timeout
                    while timeout_remaining > 0:
                        await asyncio.sleep(0.5)
                        timeout_remaining -= 0.5
                        
                        exec_data = session_data['executions'].get(msg_id)
                        if exec_data and exec_data['status'] in ['completed', 'error', 'cancelled']:
                            # Check if we should stop on error
                            if exec_data['status'] == 'error' and session_data.get('stop_on_error', False):
                                logger.warning(f"Execution failed for cell {cell_index}, clearing remaining queue (stop_on_error=True)")
                                # Clear remaining queue items
                                while not session_data['execution_queue'].empty():
                                    try:
                                        cancelled_request = session_data['execution_queue'].get_nowait()
                                        if cancelled_request is not None:
                                            # Mark as cancelled
                                            cancelled_id = cancelled_request['exec_id']
                                            for msg_id_cancel, data_cancel in session_data['executions'].items():
                                                if data_cancel.get('id') == cancelled_id:
                                                    data_cancel['status'] = 'cancelled'
                                                    data_cancel['error'] = f"Cancelled due to error in cell {cell_index}"
                                                    break
                                            session_data['execution_queue'].task_done()
                                    except asyncio.QueueEmpty:
                                        break
                            break
                    else:
                        # Timeout occurred
                        logger.warning(f"Execution timeout for cell {cell_index} in {nb_path}")
                        if msg_id in session_data['executions']:
                            session_data['executions'][msg_id]['status'] = 'timeout'
                            session_data['executions'][msg_id]['error'] = f"Execution exceeded {self.execution_timeout}s timeout"
                        
                        # If stop_on_error, also stop on timeout
                        if session_data.get('stop_on_error', False):
                            logger.warning(f"Execution timeout, clearing remaining queue (stop_on_error=True)")
                            while not session_data['execution_queue'].empty():
                                try:
                                    cancelled_request = session_data['execution_queue'].get_nowait()
                                    if cancelled_request is not None:
                                        cancelled_id = cancelled_request['exec_id']
                                        for msg_id_cancel, data_cancel in session_data['executions'].items():
                                            if data_cancel.get('id') == cancelled_id:
                                                data_cancel['status'] = 'cancelled'
                                                data_cancel['error'] = f"Cancelled due to timeout in cell {cell_index}"
                                                break
                                        session_data['execution_queue'].task_done()
                                except asyncio.QueueEmpty:
                                    break
                    
                except Exception as e:
                    logger.error(f"Error executing cell {cell_index} in {nb_path}: {e}")
                    # Mark execution as failed
                    if exec_id:
                        for msg_id, data in session_data['executions'].items():
                            if data['id'] == exec_id:
                                data['status'] = 'error'
                                data['error'] = str(e)
                                break
                    
                    # If stop_on_error, clear remaining queue
                    if session_data.get('stop_on_error', False):
                        logger.warning(f"Exception during execution, clearing remaining queue (stop_on_error=True)")
                        while not session_data['execution_queue'].empty():
                            try:
                                cancelled_request = session_data['execution_queue'].get_nowait()
                                if cancelled_request is not None:
                                    session_data['execution_queue'].task_done()
                            except asyncio.QueueEmpty:
                                break
                finally:
                    # Mark task as done
                    session_data['execution_queue'].task_done()
        
        except asyncio.CancelledError:
            logger.info(f"Queue processor cancelled for {nb_path}")
        except Exception as e:
            logger.error(f"Queue processor error for {nb_path}: {e}")

    def _finalize_execution(self, nb_path: str, exec_data: Dict):
        """Saves results to the actual .ipynb file and processes images with provenance tracking"""
        try:
            # 1. Save Assets and get text summary
            assets_dir = str(Path(nb_path).parent / "assets")
            text_summary = utils.sanitize_outputs(exec_data['outputs'], assets_dir)
            exec_data['text_summary'] = text_summary
            
            # 2. Get Cell content for content hashing
            abs_path = str(Path(nb_path).resolve())
            execution_hash = None
            
            try:
                # Load notebook to get Cell info
                with open(nb_path, 'r', encoding='utf-8') as f:
                    nb = nbformat.read(f, as_version=4)
                
                # Verify index is valid
                if 0 <= exec_data['cell_index'] < len(nb.cells):
                    cell = nb.cells[exec_data['cell_index']]
                    execution_hash = utils.get_cell_hash(cell.source)
                else:
                    logger.warning(f"Cell index {exec_data['cell_index']} out of range")
                    
            except Exception as e:
                logger.warning(f"Could not compute hash: {e}")
            
            # 3. Prepare metadata for injection into .ipynb
            metadata_update = {}
            if execution_hash:
                try:
                    env_info = self.sessions[abs_path].get('env_info', {})
                    
                    metadata_update = {
                        "execution_hash": execution_hash,
                        "execution_timestamp": datetime.datetime.now().isoformat(),
                        "kernel_env_name": env_info.get('env_name', 'unknown'),
                        "agent_run_id": str(uuid.uuid4())
                    }
                except Exception as e:
                    logger.warning(f"Failed to prepare metadata: {e}")
            
            # 4. Write to Notebook File WITH metadata injection
            notebook.save_cell_execution(
                nb_path, 
                exec_data['cell_index'], 
                exec_data['outputs'], 
                exec_data.get('execution_count'),
                metadata_update=metadata_update if metadata_update else None
            )
        except Exception as e:
            exec_data['status'] = 'failed_save'
            exec_data['error'] = str(e)
            logger.error(f"Failed to finalize execution: {e}")

    async def execute_cell_async(self, nb_path: str, cell_index: int, code: str, exec_id: Optional[str] = None) -> Optional[str]:
        """Submits execution to the queue and returns an ID immediately."""
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return None
            
        session = self.sessions[abs_path]
        
        # HEAL CHECK: If this is an inspection or system tool, ensure helper exists
        # If the kernel restarted, we might not know, so we ensure it's available.
        if "_mcp_inspect" in code and "def _mcp_inspect" not in code:
             code = INSPECT_HELPER_CODE + "\n" + code
        
        # Generate execution ID if not provided
        if not exec_id:
            exec_id = str(uuid.uuid4())
        
        # Track as queued immediately (fixes race condition with status checks)
        session['queued_executions'][exec_id] = {
            'cell_index': cell_index,
            'code': code,
            'status': 'queued',
            'queued_time': asyncio.get_event_loop().time()
        }
        
        # Create execution request
        exec_request = {
            'cell_index': cell_index,
            'code': code,
            'exec_id': exec_id
        }
        
        # Enqueue the execution
        await session['execution_queue'].put(exec_request)
        
        return exec_id

    def get_execution_status(self, nb_path: str, exec_id: str):
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return {"status": "error", "message": "Kernel not found"}
            
        session = self.sessions[abs_path]
        
        # Check if still in queue (not started processing yet)
        if exec_id in session['queued_executions']:
            queued_data = session['queued_executions'][exec_id]
            return {
                "status": "queued",
                "output": "",
                "cell_index": queued_data['cell_index'],
                "intermediate_outputs_count": 0
            }
        
        # Look for the execution by ID in active executions
        target_data = None
        for msg_id, data in session['executions'].items():
            if data['id'] == exec_id:
                target_data = data
                break
                
        if not target_data:
            return {"status": "not_found"}
            
        return {
            "status": target_data['status'],
            "output": target_data['text_summary'],
            "intermediate_outputs_count": len(target_data['outputs'])
        }

    async def get_kernel_info(self, nb_path: str):
        """
        DEPRECATED: Use get_variable_info for specific variables instead.
        Returns overview of all kernel variables (can be large).
        """
        # 
        # If we want synchronous-like behavior on top of the async listener:
        # We submit the task, and then we poll `get_execution_status` internally until done.
        
        code = """
import json
import sys
def _get_var_info():
    info = []
    # Get user variables (exclude imports and dunder methods)
    for name, value in list(globals().items()):
        if name.startswith("_") or hasattr(value, '__module__') and value.__module__ == 'builtins':
            continue
        if isinstance(value, type(sys)): continue # Skip modules
        v_type = type(value).__name__
        v_str = str(value)[:100] 
        details = {}
        if v_type == 'DataFrame' or 'pandas.core.frame.DataFrame' in str(type(value)):
            try:
                v_str = f"DataFrame: {value.shape}"
                details['columns'] = list(value.columns)
                details['dtypes'] = [str(d) for d in value.dtypes.values]
                details['head'] = value.head(3).to_dict(orient='records')
            except Exception: pass
        elif hasattr(value, '__len__') and not isinstance(value, str):
             v_str = f"{v_type}: len={len(value)}"
        info.append({"name": name, "type": v_type, "preview": v_str, "details": details})
    return json.dumps(info)
print(_get_var_info())
"""
        return await self._run_and_wait_internal(nb_path, code)

    async def save_checkpoint(self, notebook_path: str, checkpoint_name: str):
        """Snapshot the kernel heap (variables) to disk."""
        session = self.sessions.get(str(Path(notebook_path).resolve()))
        if not session: return "No session"
        
        # Execute dill dump inside the kernel
        # We save to a hidden .mcp folder next to the notebook
        ckpt_path = Path(notebook_path).parent / ".mcp" / f"{checkpoint_name}.pkl"
        # Ensure directory exists on server side just in case, though kernel writes it
        ckpt_path.parent.mkdir(exist_ok=True, parents=True)
        
        # Path for the kernel (cross-platform safe)
        path_str = str(ckpt_path).replace("\\", "\\\\")
        
        code = f"""
import dill
import os
import pickle

try:
    os.makedirs(os.path.dirname(r'{path_str}'), exist_ok=True)
    
    safe_state = {{}}
    excluded_vars = []
    ignored = ['In', 'Out', 'exit', 'quit', 'get_ipython'] 

    # Iterate over user variables only (skip system dunders)
    user_vars = {{k:v for k,v in globals().items() if not k.startswith('_') and k not in ignored}}

    for k, v in user_vars.items():
        try:
            # Test pickleability in memory first
            dill.dumps(v)
            safe_state[k] = v
        except:
            excluded_vars.append(k)

    # Save only the safe state
    with open(r'{path_str}', 'wb') as f:
        dill.dump(safe_state, f)

    msg = f"Checkpoint saved. Preserved {{len(safe_state)}} variables."
    if excluded_vars:
        msg += f" Skipped {{len(excluded_vars)}} complex objects: {{', '.join(excluded_vars)}}"
    print(msg)

except ImportError:
    print("Error: 'dill' is not installed in the kernel environment. Please run '!pip install dill' first.")
except Exception as e:
    print(f"Checkpoint error: {{e}}")
"""
        # Use -1 index for internal commands
        await self.execute_cell_async(notebook_path, -1, code)
        return f"State saved to {ckpt_path}"

    async def load_checkpoint(self, notebook_path: str, checkpoint_name: str):
        """Restore the kernel heap from disk."""
        ckpt_path = Path(notebook_path).parent / ".mcp" / f"{checkpoint_name}.pkl"
        path_str = str(ckpt_path).replace("\\", "\\\\")
        
        code = f"""
try:
    import dill
    if not os.path.exists(r'{path_str}'):
        print(f"Checkpoint not found: {path_str}")
    else:
        with open(r'{path_str}', 'rb') as f:
            # We used plain dump, so we load a dict
            state_dict = dill.load(f)
            # Update globals with the loaded state
            globals().update(state_dict)
        print(f"State restored ({{len(state_dict)}} variables)")
except Exception as e:
    print(f"Restore error: {{e}}")
"""
        await self.execute_cell_async(notebook_path, -1, code)
        return "State restored."

    async def get_variable_info(self, nb_path: str, var_name: str):
        """
        Surgical inspection of a specific variable in the kernel.
        Prevents context overflow from dumping all globals.
        """
        code = f"""
import json
import sys

def _inspect_var():
    var_name = '{var_name}'
    if var_name not in globals():
        return json.dumps({{"error": f"Variable '{{var_name}}' not found"}})
    
    value = globals()[var_name]
    v_type = type(value).__name__
    result = {{"name": var_name, "type": v_type}}
    
    # Type-specific inspection
    if 'DataFrame' in str(type(value)):
        try:
            result['shape'] = value.shape
            result['columns'] = list(value.columns)
            result['dtypes'] = {{col: str(dtype) for col, dtype in value.dtypes.items()}}
            result['head'] = value.head(5).to_dict(orient='records')
            result['memory_usage'] = value.memory_usage(deep=True).sum()
        except Exception as e:
            result['error'] = str(e)
    elif hasattr(value, '__len__') and not isinstance(value, str):
        result['length'] = len(value)
        result['preview'] = str(value)[:200]
    elif isinstance(value, (int, float, str, bool)):
        result['value'] = value
    else:
        result['preview'] = str(value)[:200]
    
    return json.dumps(result, indent=2, default=str)

print(_inspect_var())
"""
        return await self._run_and_wait_internal(nb_path, code)

    async def _run_and_wait_internal(self, nb_path: str, code: str):
        """Internal helper to run code via the async system and wait for result."""
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions: return "Error: No kernel."
        
        # We use cell_index -1 to denote internal/temporary
        exec_id = await self.execute_cell_async(nb_path, -1, code)
        if not exec_id: return "Error starting internal execution."
        
        # Wait loop
        for _ in range(20): # Write max wait 10s (20 * 0.5)
            await asyncio.sleep(0.5)
            status = self.get_execution_status(nb_path, exec_id)
            if status['status'] in ['completed', 'error']:
                return status['output']
        
        return "Error: Timeout waiting for internal command."

    async def run_simple_code(self, nb_path: str, code: str):
         return await self._run_and_wait_internal(nb_path, code)

    async def stop_kernel(self, nb_path: str):
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions: return "No running kernel."
        
        session = self.sessions[abs_path]
        
        # Signal queue processor to stop
        if session.get('queue_processor_task'):
            await session['execution_queue'].put(None)  # Shutdown signal
            session['queue_processor_task'].cancel()
            try:
                await session['queue_processor_task']
            except asyncio.CancelledError:
                pass
        
        # Cancel Listener
        if session['listener_task']:
            session['listener_task'].cancel()
            try:
                await session['listener_task']
            except asyncio.CancelledError:
                pass

        session['kc'].stop_channels()
        await session['km'].shutdown_kernel()
        del self.sessions[abs_path]
        return "Kernel shutdown."

    async def cancel_execution(self, nb_path: str, exec_id: Optional[str] = None):
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions: return "No kernel."
        
        session = self.sessions[abs_path]
        await session['km'].interrupt_kernel()
        
        # We manually mark the specific execution as cancelled if found
        if exec_id is not None:
            for msg_id, data in session['executions'].items():
                if data['id'] == exec_id and data['status'] == 'running':
                    data['status'] = 'cancelled'
                
        return "Kernel interrupted."

    async def shutdown_all(self):
        """Kills all running kernels and cleans up persisted session files."""
        for abs_path, session in list(self.sessions.items()):
            if session.get('listener_task'):
                session['listener_task'].cancel()
            try:
                await session['km'].shutdown_kernel(now=True)
                # Remove persisted session info
                self._remove_persisted_session(abs_path)
            except Exception as e:
                logging.error(f"Error shutting down kernel for {abs_path}: {e}")
        self.sessions.clear()

    # --- Preserved Helper Methods ---

    async def install_package(self, nb_path: str, package_name: str):
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
             return "Error: No running kernel to install into."
        
        session = self.sessions[abs_path]
        km = session['km']
        cmd = km.kernel_cmd
        if not cmd:
             return "Error: Could not determine kernel python path."
        
        python_executable = cmd[0]
        
        # Run pip install
        proc = await asyncio.create_subprocess_exec(
            python_executable, "-m", "pip", "install", package_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        output = f"Stdout: {stdout.decode()}\nStderr: {stderr.decode()}"
        if proc.returncode == 0:
            return f"Successfully installed {package_name}.\n{output}"
        else:
            return f"Failed to install {package_name}.\n{output}"

    async def list_packages(self, nb_path: str):
         # This uses run_simple_code currently in main, but we can implement it here too
         pass # Using main.py's implementation which calls run_simple_code

    async def interrupt_kernel(self, nb_path: str):
        return await self.cancel_execution(nb_path, None)

    async def restart_kernel(self, nb_path: str):
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
             return "Error: No running kernel."
        session = self.sessions[abs_path]
        await session['km'].restart_kernel()
        # Note: Restarting might break the listener connection? 
        # Typically jupyter_client handles this, but if channels die we might need to recreate them.
        # For now, assume it recovers or user must restart kernel via stop/start if it breaks.
        return "Kernel restarted."
    
    def list_environments(self):
        """Scans for potential Python environments."""
        envs = []
        
        # 1. Current System Python
        envs.append({"name": "System/Global", "path": sys.executable})
        
        # 2. Check common locations relative to user home
        home = Path.home()
        candidates = [
            home / ".virtualenvs",
            home / "miniconda3" / "envs",
            home / "anaconda3" / "envs",
            Path("."), # Current folder
            Path(".venv"), 
            Path("venv"),
            Path("env")
        ]
        
        for folder in candidates:
            if folder.exists():
                if (folder / "bin" / "python").exists():
                    envs.append({"name": f"Venv ({folder.name})", "path": str(folder)})
                elif (folder / "Scripts" / "python.exe").exists():
                    envs.append({"name": f"Venv ({folder.name})", "path": str(folder)})
                elif folder.is_dir():
                    # Scan subfolders (common for .virtualenvs or conda)
                    for sub in folder.iterdir():
                        if sub.is_dir():
                            if (sub / "bin" / "python").exists():
                                envs.append({"name": f"Found: {sub.name}", "path": str(sub)})

        return envs

    def get_kernel_resources(self, nb_path: str) -> Dict[str, Any]:
        """
        [PHASE 3.4] Get CPU and RAM usage of the kernel process.
        Returns resource metrics for monitoring and auto-restart logic.
        """
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return {"error": "No active kernel"}
        
        # Lazy import psutil to prevent startup crashes on systems with broken binary wheels
        try:
            import psutil
        except ImportError:
            return {"error": "psutil not installed. Install with: pip install psutil"}
        
        try:
            km = self.sessions[abs_path]['km']
            
            # Safely get PID (same pattern as start_kernel)
            if not hasattr(km, 'kernel') or not km.kernel:
                return {"error": "Kernel process not found"}
            
            pid = getattr(km.kernel, 'pid', None)
            if not pid:
                return {"error": "Kernel PID not available"}
            
            proc = psutil.Process(pid)
            
            # Get children processes (kernels sometimes spawn subprocesses)
            children = proc.children(recursive=True)
            total_mem = proc.memory_info().rss
            total_cpu = proc.cpu_percent(interval=0.1)
            
            for child in children:
                try:
                    total_mem += child.memory_info().rss
                    total_cpu += child.cpu_percent(interval=0.1)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            return {
                "status": "active",
                "pid": pid,
                "memory_mb": round(total_mem / 1024 / 1024, 2),
                "memory_percent": round(proc.memory_percent(), 1),
                "cpu_percent": round(total_cpu, 1),
                "num_threads": proc.num_threads(),
                "num_children": len(children)
            }
        except Exception as e:
            # Catch all exceptions including psutil.NoSuchProcess
            # Check if it's a zombie kernel specifically
            if "NoSuchProcess" in str(type(e).__name__):
                return {"error": "Kernel process no longer exists (zombie state)"}
            return {"error": str(e)}

    def get_session(self, nb_path: str):
        abs_path = str(Path(nb_path).resolve())
        return self.sessions.get(abs_path)
