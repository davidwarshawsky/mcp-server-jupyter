"""
Environment detection and Python executable discovery.
Provides comprehensive cross-platform support for detecting and validating
Python environments (venv, virtualenv, conda, pyenv, poetry, pipenv, system).
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

def find_python_executables() -> List[Dict[str, Any]]:
    """
    Discovers all Python interpreters on the system.
    Scans PATH and common installation locations.
    
    Returns:
        List of dicts with 'path', 'version', 'type', 'env_name' keys
    """
    executables = []
    seen_paths = set()
    
    # 1. System Python (current interpreter)
    current_exe = sys.executable
    if current_exe not in seen_paths:
        seen_paths.add(current_exe)
        version_info = get_python_version(current_exe)
        executables.append({
            'path': current_exe,
            'version': version_info['version'],
            'type': 'system',
            'env_name': 'current',
            'valid': True,
            'details': version_info
        })
    
    # 2. Scan PATH
    path_env = os.environ.get('PATH', '')
    for path_dir in path_env.split(os.pathsep):
        if not path_dir or not os.path.exists(path_dir):
            continue
        
        # Look for python executables
        for name in ['python', 'python3', 'python.exe', 'python3.exe']:
            exe_path = os.path.join(path_dir, name)
            if os.path.isfile(exe_path) and os.access(exe_path, os.X_OK):
                real_path = os.path.realpath(exe_path)
                if real_path not in seen_paths:
                    seen_paths.add(real_path)
                    version_info = get_python_version(real_path)
                    if version_info['valid']:
                        env_type, env_name = detect_environment_type(real_path)
                        executables.append({
                            'path': real_path,
                            'version': version_info['version'],
                            'type': env_type,
                            'env_name': env_name,
                            'valid': True,
                            'details': version_info
                        })
    
    # 3. Scan common conda locations
    conda_executables = find_conda_environments()
    for conda_exe in conda_executables:
        if conda_exe['path'] not in seen_paths:
            seen_paths.add(conda_exe['path'])
            executables.append(conda_exe)
    
    # 4. Scan common venv locations
    venv_executables = find_venv_environments()
    for venv_exe in venv_executables:
        if venv_exe['path'] not in seen_paths:
            seen_paths.add(venv_exe['path'])
            executables.append(venv_exe)
    
    return executables

def get_python_version(python_path: str) -> Dict[str, Any]:
    """
    Gets Python version and additional info by executing the interpreter.
    
    Returns:
        Dict with 'version', 'valid', 'major', 'minor', 'micro', 'pip_available'
    """
    try:
        result = subprocess.run(
            [python_path, '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        version_str = result.stdout.strip() or result.stderr.strip()
        # Format: "Python 3.10.5"
        version = version_str.replace('Python ', '').strip()
        parts = version.split('.')
        
        # Check pip availability
        pip_result = subprocess.run(
            [python_path, '-m', 'pip', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        pip_available = pip_result.returncode == 0
        
        return {
            'version': version,
            'valid': True,
            'major': int(parts[0]) if len(parts) > 0 else None,
            'minor': int(parts[1]) if len(parts) > 1 else None,
            'micro': int(parts[2]) if len(parts) > 2 else None,
            'pip_available': pip_available
        }
    except Exception as e:
        return {
            'version': 'unknown',
            'valid': False,
            'major': None,
            'minor': None,
            'micro': None,
            'pip_available': False,
            'error': str(e)
        }

def detect_environment_type(python_path: str) -> Tuple[str, str]:
    """
    Detects the type of Python environment.
    
    Returns:
        Tuple of (env_type, env_name)
        env_type: 'venv', 'virtualenv', 'conda', 'pyenv', 'poetry', 'pipenv', 'system'
    """
    python_path_obj = Path(python_path).resolve()
    
    # Check for conda
    if 'conda' in str(python_path_obj).lower() or 'anaconda' in str(python_path_obj).lower() or 'miniconda' in str(python_path_obj).lower():
        # Extract environment name
        parts = python_path_obj.parts
        for i, part in enumerate(parts):
            if part == 'envs' and i + 1 < len(parts):
                return ('conda', parts[i + 1])
        return ('conda', 'base')
    
    # Check for venv/virtualenv
    parent_dirs = [python_path_obj.parent.parent, python_path_obj.parent.parent.parent]
    for parent in parent_dirs:
        if (parent / 'pyvenv.cfg').exists():
            return ('venv', parent.name)
        if (parent / 'bin' / 'activate').exists() or (parent / 'Scripts' / 'activate').exists():
            return ('virtualenv', parent.name)
    
    # Check for pyenv
    if 'pyenv' in str(python_path_obj).lower():
        return ('pyenv', python_path_obj.parent.name)
    
    # Check for poetry
    if 'poetry' in str(python_path_obj).lower() or 'pypoetry' in str(python_path_obj).lower():
        return ('poetry', python_path_obj.parent.parent.name)
    
    # Check for pipenv
    if 'pipenv' in str(python_path_obj).lower() or '.virtualenvs' in str(python_path_obj):
        return ('pipenv', python_path_obj.parent.parent.name)
    
    return ('system', 'system')

def find_conda_environments() -> List[Dict[str, Any]]:
    """Finds all conda environments."""
    environments = []
    
    # Try conda command
    conda_exe = shutil.which('conda')
    if conda_exe:
        try:
            result = subprocess.run(
                [conda_exe, 'env', 'list', '--json'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for env_path in data.get('envs', []):
                    env_path = Path(env_path)
                    # Find python executable
                    if os.name == 'nt':
                        python_exe = env_path / 'python.exe'
                    else:
                        python_exe = env_path / 'bin' / 'python'
                    
                    if python_exe.exists():
                        version_info = get_python_version(str(python_exe))
                        environments.append({
                            'path': str(python_exe),
                            'version': version_info['version'],
                            'type': 'conda',
                            'env_name': env_path.name,
                            'valid': version_info['valid'],
                            'details': version_info
                        })
        except Exception:
            pass
    
    # Also check common conda locations
    home = Path.home()
    common_locations = [
        home / 'miniconda3' / 'envs',
        home / 'anaconda3' / 'envs',
        home / 'miniforge3' / 'envs',
        Path('C:\\ProgramData\\Miniconda3\\envs') if os.name == 'nt' else None,
        Path('C:\\ProgramData\\Anaconda3\\envs') if os.name == 'nt' else None,
    ]
    
    for location in common_locations:
        if location and location.exists():
            for env_dir in location.iterdir():
                if env_dir.is_dir():
                    if os.name == 'nt':
                        python_exe = env_dir / 'python.exe'
                    else:
                        python_exe = env_dir / 'bin' / 'python'
                    
                    if python_exe.exists():
                        version_info = get_python_version(str(python_exe))
                        # Avoid duplicates by checking if already in list
                        if not any(e['path'] == str(python_exe) for e in environments):
                            environments.append({
                                'path': str(python_exe),
                                'version': version_info['version'],
                                'type': 'conda',
                                'env_name': env_dir.name,
                                'valid': version_info['valid'],
                                'details': version_info
                            })
    
    return environments

def find_venv_environments() -> List[Dict[str, Any]]:
    """Finds venv/virtualenv environments in common locations."""
    environments = []
    
    home = Path.home()
    cwd = Path.cwd()
    
    # Common locations
    search_locations = [
        cwd / '.venv',
        cwd / 'venv',
        cwd / 'env',
        home / '.virtualenvs',
        home / 'venvs',
    ]
    
    for location in search_locations:
        if location.exists() and location.is_dir():
            # Check if it's a virtual environment
            if os.name == 'nt':
                python_exe = location / 'Scripts' / 'python.exe'
            else:
                python_exe = location / 'bin' / 'python'
            
            if python_exe.exists():
                version_info = get_python_version(str(python_exe))
                env_type, env_name = detect_environment_type(str(python_exe))
                environments.append({
                    'path': str(python_exe),
                    'version': version_info['version'],
                    'type': env_type,
                    'env_name': env_name,
                    'valid': version_info['valid'],
                    'details': version_info
                })
    
    # Also scan .virtualenvs for multiple environments
    virtualenvs_dir = home / '.virtualenvs'
    if virtualenvs_dir.exists():
        for env_dir in virtualenvs_dir.iterdir():
            if env_dir.is_dir():
                if os.name == 'nt':
                    python_exe = env_dir / 'Scripts' / 'python.exe'
                else:
                    python_exe = env_dir / 'bin' / 'python'
                
                if python_exe.exists():
                    # Check if already added
                    if not any(e['path'] == str(python_exe) for e in environments):
                        version_info = get_python_version(str(python_exe))
                        env_type, env_name = detect_environment_type(str(python_exe))
                        environments.append({
                            'path': str(python_exe),
                            'version': version_info['version'],
                            'type': env_type,
                            'env_name': env_name,
                            'valid': version_info['valid'],
                            'details': version_info
                        })
    
    return environments

def validate_python_executable(python_path: str) -> Dict[str, Any]:
    """
    Validates a Python executable.
    
    Returns:
        Dict with 'valid', 'exists', 'executable', 'version', 'error' keys
    """
    result = {
        'valid': False,
        'exists': False,
        'executable': False,
        'version': None,
        'error': None
    }
    
    path = Path(python_path)
    
    # Check if file exists
    if not path.exists():
        result['error'] = f"File does not exist: {python_path}"
        return result
    
    result['exists'] = True
    
    # Check if executable
    if not os.access(python_path, os.X_OK):
        result['error'] = f"File is not executable: {python_path}"
        return result
    
    result['executable'] = True
    
    # Try to get version
    version_info = get_python_version(python_path)
    if not version_info['valid']:
        result['error'] = f"Failed to execute Python: {version_info.get('error', 'unknown')}"
        return result
    
    result['valid'] = True
    result['version'] = version_info['version']
    
    return result

def auto_detect_environment(notebook_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Automatically detects the best Python environment to use.
    If notebook_path is provided, looks for .venv or environment in notebook directory.
    
    Returns:
        Dict with 'python_path', 'env_type', 'env_name', 'version'
    """
    # 1. If notebook path provided, check for local environments
    if notebook_path:
        notebook_dir = Path(notebook_path).parent
        
        # Check for .venv in notebook directory
        for venv_name in ['.venv', 'venv', 'env']:
            venv_path = notebook_dir / venv_name
            if venv_path.exists():
                if os.name == 'nt':
                    python_exe = venv_path / 'Scripts' / 'python.exe'
                else:
                    python_exe = venv_path / 'bin' / 'python'
                
                if python_exe.exists():
                    version_info = get_python_version(str(python_exe))
                    if version_info['valid']:
                        return {
                            'python_path': str(python_exe),
                            'env_type': 'venv',
                            'env_name': venv_name,
                            'version': version_info['version'],
                            'method': 'local_venv'
                        }
    
    # 2. Check for active virtual environment
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        return {
            'python_path': sys.executable,
            'env_type': 'venv',
            'env_name': Path(sys.prefix).name,
            'version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'method': 'active_venv'
        }
    
    # 3. Check CONDA_DEFAULT_ENV
    conda_env = os.environ.get('CONDA_DEFAULT_ENV')
    if conda_env:
        return {
            'python_path': sys.executable,
            'env_type': 'conda',
            'env_name': conda_env,
            'version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'method': 'active_conda'
        }
    
    # 4. Default to system Python
    return {
        'python_path': sys.executable,
        'env_type': 'system',
        'env_name': 'system',
        'version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'method': 'system_default'
    }

def create_venv(path: str, python_executable: str = None) -> Dict[str, Any]:
    """
    Creates a new virtual environment.
    
    Args:
        path: Path where the venv will be created
        python_executable: Optional Python executable to use (defaults to sys.executable)
    
    Returns:
        Dict with 'success', 'venv_path', 'python_path', 'error'
    """
    if python_executable is None:
        python_executable = sys.executable
    
    try:
        # Create venv
        result = subprocess.run(
            [python_executable, '-m', 'venv', path],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            return {
                'success': False,
                'venv_path': None,
                'python_path': None,
                'error': result.stderr
            }
        
        # Get Python path in new venv
        venv_path = Path(path)
        if os.name == 'nt':
            python_path = venv_path / 'Scripts' / 'python.exe'
        else:
            python_path = venv_path / 'bin' / 'python'
        
        return {
            'success': True,
            'venv_path': str(venv_path),
            'python_path': str(python_path),
            'error': None
        }
    except Exception as e:
        return {
            'success': False,
            'venv_path': None,
            'python_path': None,
            'error': str(e)
        }
