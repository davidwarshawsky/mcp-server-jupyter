import os
import sys
import asyncio
import uuid
import json
import logging
import nbformat
import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from jupyter_client.manager import AsyncKernelManager
from src import notebook, utils

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

    async def start_kernel(self, nb_path: str, venv_path: Optional[str] = None):
        abs_path = str(Path(nb_path).resolve())
        # Determine the Notebook's directory to set as CWD
        notebook_dir = str(Path(nb_path).parent.resolve())

        if abs_path in self.sessions: 
            return f"Kernel already running for {abs_path}"
        
        km = AsyncKernelManager()
        
        # 1. Handle Environment
        py_exe = sys.executable
        env_name = "system"
        
        if venv_path:
            py_exe = self.get_python_path(venv_path)
            env_name = Path(venv_path).name
            # Better: if venv_path provided, ensure py_exe starts with it.
            if venv_path and not str(py_exe).lower().startswith(str(Path(venv_path).resolve()).lower()):
                 return f"Error: Could not find python executable in {venv_path}"

            # Force Jupyter to use our Venv Python
            km.kernel_cmd = [py_exe, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
        
        # 2. Start Kernel with Correct CWD
        await km.start_kernel(cwd=notebook_dir)
        
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
        startup_code = """
%load_ext autoreload
%autoreload 2

# [PHASE 3.3] Force static rendering for interactive visualization libraries
# This allows AI agents to "see" plots that would otherwise be JavaScript-based
import os
try:
    import matplotlib
    matplotlib.use('Agg')  # Headless backend for matplotlib
    get_ipython().run_line_magic('matplotlib', 'inline')
except ImportError:
    pass  # matplotlib not installed, skip

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
"""
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
        
        # Safely get PID
        pid = "unknown"
        if hasattr(km, 'kernel') and km.kernel:
            pid = getattr(km.kernel, 'pid', 'unknown')
                 
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
            
            # 2. Build provenance metadata
            abs_path = str(Path(nb_path).resolve())
            env_info = self.sessions[abs_path]['env_info']
            
            provenance = {
                "execution_timestamp": datetime.datetime.now().isoformat(),
                "kernel_env_name": env_info['env_name'],
                "kernel_python_path": env_info['python_path'],
                "kernel_start_time": env_info['start_time'],
                "agent_tool": "mcp-jupyter"
            }
            
            # 3. Write to Notebook File with provenance
            notebook.save_cell_execution(
                nb_path, 
                exec_data['cell_index'], 
                exec_data['outputs'], 
                exec_data.get('execution_count'),
                metadata_update=provenance  # NEW: Inject provenance metadata
            )
        except Exception as e:
            exec_data['status'] = 'failed_save'
            exec_data['error'] = str(e)
            logger.error(f"Failed to finalize execution: {e}")

    async def execute_cell_async(self, nb_path: str, cell_index: int, code: str) -> Optional[str]:
        """Submits execution to the queue and returns an ID immediately."""
        abs_path = str(Path(nb_path).resolve())
        if abs_path not in self.sessions:
            return None
            
        session = self.sessions[abs_path]
        
        # Generate execution ID
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
    
    return json.dumps(result, indent=2)

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
        """Kills all running kernels."""
        for abs_path, session in list(self.sessions.items()):
            if session.get('listener_task'):
                session['listener_task'].cancel()
            try:
                await session['km'].shutdown_kernel(now=True)
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
