"""
Git-Safe Notebook Saving and Repository Management

Tools for Agents to work safely with Git repositories:
- Clean notebook saves (strip volatile metadata)
- Git filter configuration (nbstripout)
- Defensive branching (sandbox for agent work)
"""

import os
import sys
import json
import subprocess
import tempfile
import nbformat
from pathlib import Path
from typing import Optional, Dict, Any


def save_notebook_clean(notebook_path: str, strip_outputs: bool = False) -> str:
    """
    Save notebook in Git-friendly format.
    
    Keeps outputs (graphs/tables) for GitHub viewing BUT strips:
    - execution_count (set to null)
    - Volatile cell metadata (timestamps, collapsed state, scrolled)
    - Optionally strips all outputs if strip_outputs=True
    
    This is the tool Agents should call before git commit to minimize
    merge conflicts while keeping notebooks readable on GitHub.
    
    Args:
        notebook_path: Path to notebook file
        strip_outputs: If True, remove all outputs (for sensitive data). Default False.
    
    Returns:
        Success message with count of cleaned cells
    """
    from src.notebook import _atomic_write_notebook
    
    path = Path(notebook_path)
    if not path.exists():
        return f"Error: Notebook not found: {notebook_path}"
    
    try:
        # Read notebook
        with open(path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        
        cells_cleaned = 0
        outputs_stripped = 0
        
        # Clean each cell
        for cell in nb.cells:
            if cell.cell_type == 'code':
                # Strip execution_count (major source of Git conflicts)
                if cell.execution_count is not None:
                    cell.execution_count = None
                    cells_cleaned += 1
                
                # Strip outputs if requested
                if strip_outputs and cell.outputs:
                    cell.outputs = []
                    outputs_stripped += 1
                
                # Strip volatile cell metadata
                volatile_keys = ['collapsed', 'scrolled', 'execution']
                for key in volatile_keys:
                    if key in cell.metadata:
                        del cell.metadata[key]
                        cells_cleaned += 1
        
        # Strip volatile notebook metadata
        if 'widgets' in nb.metadata:
            del nb.metadata['widgets']
        
        # Write atomically
        _atomic_write_notebook(nb, path)
        
        msg = f"Cleaned {cells_cleaned} cells in {path.name}"
        if outputs_stripped > 0:
            msg += f" (stripped {outputs_stripped} outputs)"
        
        return msg
    
    except Exception as e:
        return f"Error cleaning notebook: {str(e)}"


def setup_git_filters(repo_path: str = ".") -> str:
    """
    Configure Git filters to auto-clean notebooks on commit.
    
    Installs nbstripout filter that:
    - Strips execution_count on commit
    - Strips volatile metadata
    - Keeps outputs in working tree (for local viewing)
    - Prevents metadata noise in Git history
    
    This is a one-time setup per repository. Agent should call this
    when starting work on a new repo with notebooks.
    
    Args:
        repo_path: Path to Git repository root (default: current directory)
    
    Returns:
        Success/error message
    """
    repo = Path(repo_path).resolve()
    
    # Check if this is a Git repo
    if not (repo / ".git").exists():
        return f"Error: {repo} is not a Git repository"
    
    try:
        # Check if nbstripout is installed
        result = subprocess.run(
            ['nbstripout', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return (
                "Error: nbstripout not installed. Install with:\n"
                "  pip install nbstripout\n"
                "Then retry setup_git_filters()."
            )
        
        # Install nbstripout filter to .git/config
        result = subprocess.run(
            ['nbstripout', '--install'],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return f"Error installing nbstripout: {result.stderr}"
        
        # Add .gitattributes entry
        gitattributes = repo / ".gitattributes"
        needs_entry = True
        
        if gitattributes.exists():
            with open(gitattributes, 'r') as f:
                if '*.ipynb filter=nbstripout' in f.read():
                    needs_entry = False
        
        if needs_entry:
            with open(gitattributes, 'a') as f:
                f.write("\n# Auto-clean Jupyter notebooks on commit\n")
                f.write("*.ipynb filter=nbstripout\n")
        
        return (
            f"Git filters configured successfully for {repo.name}\n"
            f"Notebooks will be auto-cleaned on git commit.\n"
            f"Working tree outputs preserved for local viewing."
        )
    
    except FileNotFoundError:
        return "Error: nbstripout command not found. Install with: pip install nbstripout"
    except subprocess.TimeoutExpired:
        return "Error: nbstripout command timed out"
    except Exception as e:
        return f"Error configuring Git filters: {str(e)}"


def create_agent_branch(repo_path: str = ".", branch_name: str = "") -> str:
    """
    Create Git branch for agent work (defensive branching).
    
    Safety checks:
    - Fails if working directory has uncommitted changes
    - Fails if repo is in detached HEAD state
    - Creates branch and checks it out
    
    Agent should ALWAYS work on a separate branch, then human can
    review and squash-merge. This prevents agent hallucinations from
    destroying work on main.
    
    Args:
        repo_path: Path to Git repository root
        branch_name: Branch name (default: agent/task-{timestamp})
    
    Returns:
        Success message with branch name, or error
    """
    import datetime
    
    repo = Path(repo_path).resolve()
    
    # Check if this is a Git repo
    if not (repo / ".git").exists():
        return f"Error: {repo} is not a Git repository"
    
    # Generate branch name if not provided
    if not branch_name:
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        branch_name = f"agent/task-{timestamp}"
    
    try:
        # Check for uncommitted changes
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.stdout.strip():
            return (
                "Error: Uncommitted changes detected.\n"
                "Please commit or stash changes before creating agent branch:\n"
                f"{result.stdout[:200]}"
            )
        
        # Check if we're in detached HEAD
        result = subprocess.run(
            ['git', 'symbolic-ref', '-q', 'HEAD'],
            cwd=str(repo),
            capture_output=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return "Error: Repository is in detached HEAD state. Checkout a branch first."
        
        # Get current branch for reference
        result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5
        )
        current_branch = result.stdout.strip()
        
        # Create and checkout new branch
        result = subprocess.run(
            ['git', 'checkout', '-b', branch_name],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            if "already exists" in result.stderr:
                return f"Error: Branch '{branch_name}' already exists. Choose a different name."
            return f"Error creating branch: {result.stderr}"
        
        return (
            f"✓ Created and switched to branch: {branch_name}\n"
            f"  (branched from: {current_branch})\n\n"
            f"You can now safely work on this branch.\n"
            f"When done, human can review and merge with:\n"
            f"  git checkout {current_branch}\n"
            f"  git merge --squash {branch_name}\n"
            f"  git commit -m 'Agent work: <description>'"
        )
    
    except FileNotFoundError:
        return "Error: git command not found. Is Git installed?"
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


def commit_agent_work(
    repo_path: str = ".",
    message: str = "",
    files: Optional[list] = None
) -> str:
    """
    Commit agent changes to current branch (optional helper).
    
    This is a convenience tool. Agent can also just tell human
    "I've made changes, please review and commit."
    
    Safety checks:
    - Only commits specified files (no 'git add .')
    - Refuses to commit to main/master without confirmation
    - Runs pre-commit hooks
    
    Args:
        repo_path: Path to Git repository
        message: Commit message (required)
        files: List of file paths to commit (required)
    
    Returns:
        Success message with commit hash, or error
    """
    if not message:
        return "Error: Commit message required"
    
    if not files or len(files) == 0:
        return "Error: No files specified. Provide list of files to commit."
    
    repo = Path(repo_path).resolve()
    
    if not (repo / ".git").exists():
        return f"Error: {repo} is not a Git repository"
    
    try:
        # Get current branch
        result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5
        )
        current_branch = result.stdout.strip()
        
        # Warn if on main/master
        if current_branch in ['main', 'master']:
            return (
                f"Warning: You are on branch '{current_branch}'.\n"
                f"Agent should work on a separate branch (use create_agent_branch).\n"
                f"Commit aborted for safety."
            )
        
        # Add specified files
        for file in files:
            file_path = Path(file)
            if not file_path.exists():
                return f"Error: File not found: {file}"
            
            result = subprocess.run(
                ['git', 'add', str(file)],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                return f"Error adding {file}: {result.stderr}"
        
        # Commit with message
        result = subprocess.run(
            ['git', 'commit', '-m', message],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            # Check if it's just "no changes"
            if "nothing to commit" in result.stdout.lower():
                return "No changes to commit (files already committed or unchanged)"
            return f"Error committing: {result.stderr}"
        
        # Get commit hash
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5
        )
        commit_hash = result.stdout.strip()
        
        return (
            f"✓ Committed to branch: {current_branch}\n"
            f"  Commit: {commit_hash}\n"
            f"  Files: {', '.join(files)}\n"
            f"  Message: {message}"
        )
    
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out"
    except Exception as e:
        return f"Error: {str(e)}"
