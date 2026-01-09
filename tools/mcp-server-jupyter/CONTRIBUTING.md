# Contributing to MCP Server Jupyter

Thank you for your interest in contributing! This document provides guidelines and technical details for contributing to the project.

---

## 📋 Table of Contents

1. [Getting Started](#getting-started)
2. [Development Workflow](#development-workflow)
3. [Architecture](#architecture)
4. [Design Patterns](#design-patterns)
5. [Code Style](#code-style)
6. [Testing](#testing)
7. [Adding New Features](#adding-new-features)
8. [Pull Request Process](#pull-request-process)

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10, 3.11, or 3.12
- Poetry or pip for dependency management
- Git for version control
- Basic understanding of Jupyter architecture and MCP protocol

### Setup Development Environment

```bash
# Clone repository
git clone <repository-url>
cd mcp-server-jupyter

# Install dependencies
poetry install

# Activate virtual environment
poetry shell

# Run tests to verify setup
pytest tests/ -m "not optional" -n 4
```

### Install Pre-commit Hooks (Optional)
```bash
pip install pre-commit
pre-commit install
```

---

## 🔄 Development Workflow

### Branching Strategy

We use a **feature branch workflow**:

```
main (protected)
├── feature/add-cell-metadata-tool
├── feature/improve-error-handling
├── bugfix/kernel-timeout-issue
└── docs/update-api-reference
```

### Branch Naming Convention

| Type | Prefix | Example |
|------|--------|---------|
| New Feature | `feature/` | `feature/add-streaming-execution` |
| Bug Fix | `bugfix/` | `bugfix/kernel-crash-on-error` |
| Documentation | `docs/` | `docs/update-contributing-guide` |
| Refactoring | `refactor/` | `refactor/session-manager-cleanup` |
| Testing | `test/` | `test/add-integration-tests` |

### Workflow Steps

1. **Create Feature Branch**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feature/my-new-feature
   ```

2. **Make Changes**
   - Write code following [code style guidelines](#code-style)
   - Add/update tests for new functionality
   - Update documentation if needed

3. **Format Code**
   ```bash
   black src/ tests/
   ```

4. **Run Tests**
   ```bash
   # Fast: Core tests only (~45s)
   pytest tests/ -m "not optional" -n 4
   
   # Full: All tests including optional (~86s)
   pytest tests/ -n 4
   
   # Specific test file
   pytest tests/test_session.py -v
   ```

5. **Commit Changes**
   ```bash
   git add .
   git commit -m "feat: add streaming execution support"
   ```

6. **Push Branch**
   ```bash
   git push origin feature/my-new-feature
   ```

7. **Create Pull Request**
   - Go to GitHub/GitLab and create PR
   - Fill in PR template (description, testing, breaking changes)
   - Wait for CI/CD and code review

---

## 🏗️ Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         MCP Client                          │
│                    (AI Agent / Frontend)                    │
└───────────────────────────┬─────────────────────────────────┘
                            │ MCP Protocol (JSON-RPC)
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                      main.py (MCP Server)                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Tool Registration Layer                │   │
│  │  • 25+ MCP tools registered via @server.call_tool   │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │            SessionManager (session.py)              │   │
│  │  • Kernel lifecycle management                      │   │
│  │  • Async execution queue                            │   │
│  │  • IOPub message listener                           │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         ↓                                    │
│  ┌──────────────┬──────────────┬───────────────────────┐   │
│  │ notebook.py  │ notebook_    │ utils.py / env.py     │   │
│  │ (CRUD ops)   │ ops.py       │ (helpers)             │   │
│  │              │ (cell manip) │                       │   │
│  └──────────────┴──────────────┴───────────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    Jupyter Client Library                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │          AsyncKernelManager (per notebook)           │  │
│  │  • Start/stop/restart kernel                         │  │
│  │  • Execute code                                      │  │
│  │  • Manage ZMQ channels (shell, iopub, stdin)        │  │
│  └──────────────────────┬───────────────────────────────┘  │
└─────────────────────────┼───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    IPython Kernel Process                   │
│  • Python interpreter with IPython                         │
│  • Executes code in isolated namespace                     │
│  • Sends execution results via ZMQ                         │
└─────────────────────────────────────────────────────────────┘
```

### Component Details

#### 1. `main.py` - MCP Server Entry Point
- **Responsibility**: MCP protocol implementation, tool registration
- **Key Functions**:
  - `@server.call_tool` decorators for all 25+ tools
  - Input validation and error handling
  - Response formatting for MCP protocol

#### 2. `session.py` - SessionManager
- **Responsibility**: Kernel lifecycle, async execution, state management
- **Key Data Structures**:
  ```python
  self.sessions = {
      "notebook_path": {
          'km': AsyncKernelManager,          # Kernel manager
          'kc': AsyncKernelClient,           # Kernel client
          'cwd': str,                        # Working directory
          'listener_task': asyncio.Task,     # IOPub listener
          'executions': Dict[str, Dict],     # Execution tracking
          'execution_queue': asyncio.Queue,  # Async execution queue
          'queue_processor_task': asyncio.Task,  # Queue processor
          'execution_counter': int,          # Cell execution counter
          'stop_on_error': bool,             # Error handling flag
          'env_info': Dict                   # Environment metadata
      }
  }
  ```

- **Key Methods**:
  - `start_kernel(nb_path)` - Start kernel with environment detection
  - `execute_cell_async(nb_path, cell_index, code)` - Non-blocking execution
  - `get_execution_status(nb_path, exec_id)` - Check execution status
  - `_queue_processor(nb_path)` - Background queue processor
  - `_iopub_listener(nb_path)` - IOPub message listener
  - `_finalize_execution(nb_path, exec_data)` - Save results + provenance

#### 3. `notebook.py` - Notebook CRUD Operations
- **Responsibility**: Read/write/modify notebook files
- **Key Functions**:
  - `create_notebook()` - Create new notebooks with metadata
  - `insert_cell()` / `edit_cell()` / `delete_cell()` - Cell CRUD
  - `save_cell_execution()` - Write execution results + provenance
  - `get_metadata()` / `set_metadata()` - Metadata management

#### 4. `notebook_ops.py` - Advanced Cell Manipulation
- **Responsibility**: Complex cell operations
- **Key Functions**:
  - `move_cell()` - Reorder cells
  - `copy_cell()` - Duplicate cells
  - `merge_cells()` - Combine multiple cells
  - `split_cell()` - Split cell at line
  - `change_cell_type()` - Convert cell types

#### 5. `utils.py` - Output Sanitization & Asset Management
- **Responsibility**: Clean output for LLM consumption
- **Key Functions**:
  - `sanitize_outputs()` - Main sanitization pipeline
  - `_convert_small_html_table_to_markdown()` - HTML table conversion
  - `_save_output_asset()` - Extract binary assets to disk
  - `_slice_text()` - Truncate long text safely

**Sanitization Pipeline**:
```
Raw Output → Asset Extraction → HTML Table Conversion → 
ANSI Stripping → Truncation → Clean Text
```

#### 6. `environment.py` - Environment Detection
- **Responsibility**: Detect Python environment (conda/venv/system)
- **Key Functions**:
  - `detect_environment()` - Auto-detect environment type
  - `get_python_version()` - Get interpreter version
  - Returns: `{"env_type": "conda", "env_name": "data-science", ...}`

---

## 🎨 Design Patterns

### 1. Asynchronous Execution Queue

**Problem**: Multiple cells executing concurrently can cause race conditions.

**Solution**: Queue-based execution with single worker per notebook:

```python
# High-level flow
execute_cell_async(nb_path, index, code)
    ↓
  Generate exec_id (UUID)
    ↓
  Add to execution_queue
    ↓
  Return exec_id immediately
    ↓
_queue_processor (background task)
    ↓
  Dequeue → Execute → Save results
```

**Implementation**:
```python
async def _queue_processor(self, nb_path: str):
    while True:
        exec_data = await self.execution_queue.get()
        exec_data['status'] = 'running'
        
        # Execute cell
        msg_id = self.kc.execute(exec_data['code'])
        
        # Wait for completion via IOPub listener
        # (listener updates exec_data['outputs'])
        
        exec_data['status'] = 'completed'
        self._finalize_execution(nb_path, exec_data)
```

### 2. IOPub Message Listener

**Problem**: Kernel sends execution results asynchronously via ZMQ.

**Solution**: Background task listening to IOPub channel:

```python
async def _iopub_listener(self, nb_path: str):
    while True:
        msg = await kc.get_iopub_msg(timeout=None)
        
        # Route message to correct execution
        msg_id = msg['parent_header'].get('msg_id')
        exec_data = self.find_execution_by_msg_id(msg_id)
        
        # Handle message type
        if msg['msg_type'] == 'stream':
            exec_data['outputs'].append({
                'output_type': 'stream',
                'text': msg['content']['text']
            })
        elif msg['msg_type'] == 'execute_result':
            # ... handle result
        elif msg['msg_type'] == 'error':
            # ... handle error
```

### 3. Asset Extraction with Priority

**Problem**: Multiple output formats (PNG, SVG, PDF) can bloat context.

**Solution**: Priority-based extraction (only save highest priority):

```python
ASSET_PRIORITY = {
    'application/pdf': 4,      # Highest
    'image/svg+xml': 3,
    'image/png': 2,
    'image/jpeg': 1            # Lowest
}

# In sanitize_outputs()
highest_mime = max(output['data'].keys(), key=lambda m: ASSET_PRIORITY.get(m, 0))
if ASSET_PRIORITY.get(highest_mime, 0) > 0:
    _save_output_asset(output['data'][highest_mime], mime=highest_mime)
```

### 4. Provenance Tracking

**Problem**: Can't debug "why did this cell fail today but worked yesterday?"

**Solution**: Automatic metadata injection on every execution:

```python
def _finalize_execution(self, nb_path, exec_data):
    provenance = {
        "execution_timestamp": datetime.now().isoformat(),
        "kernel_env_name": self.sessions[nb_path]['env_info']['env_name'],
        "kernel_python_path": self.sessions[nb_path]['env_info']['python_path'],
        "agent_tool": "mcp-jupyter"
    }
    
    notebook.save_cell_execution(
        nb_path,
        exec_data['cell_index'],
        outputs=exec_data['outputs'],
        metadata={'mcp_trace': provenance}
    )
```

### 5. Safe Variable Inspection

**Problem**: `eval(variable_name)` allows code injection.

**Solution**: Dictionary lookups only:

```python
# UNSAFE (old)
obj = eval(variable_name)  # Can execute arbitrary code!

# SAFE (new)
if variable_name in locals():
    obj = locals()[variable_name]
elif variable_name in globals():
    obj = globals()[variable_name]
else:
    return "Variable not found"
```

---

## 🎯 Code Style

### Black Formatter

**All code must be formatted with Black before committing.**

```bash
# Format all code
black src/ tests/

# Check formatting without changes
black --check src/ tests/
```

**Configuration** (in `pyproject.toml`):
```toml
[tool.black]
line-length = 100
target-version = ["py310", "py311", "py312"]
```

### Code Style Guidelines

1. **Line Length**: 100 characters (Black enforced)
2. **Imports**: Organize with isort or manually:
   ```python
   # Standard library
   import os
   import sys
   
   # Third-party
   import pytest
   import nbformat
   
   # Local
   from src.session import SessionManager
   ```

3. **Type Hints**: Use for function signatures:
   ```python
   def execute_cell(nb_path: str, cell_index: int) -> str:
       ...
   ```

4. **Docstrings**: Use Google style:
   ```python
   def my_function(arg1: str, arg2: int) -> bool:
       """
       Short description.
       
       Longer description with details.
       
       Args:
           arg1: Description of arg1
           arg2: Description of arg2
       
       Returns:
           Description of return value
       
       Raises:
           ValueError: When arg1 is empty
       """
   ```

5. **Error Handling**: Be specific:
   ```python
   # Good
   try:
       result = some_operation()
   except KeyError as e:
       logger.error(f"Missing key: {e}")
       raise ValueError(f"Invalid notebook structure: {e}")
   
   # Bad
   try:
       result = some_operation()
   except Exception:
       pass
   ```

---

## 🧪 Testing

### Test Structure

```
tests/
├── conftest.py                 # Fixtures and configuration
├── test_session.py             # SessionManager tests
├── test_notebook.py            # Notebook CRUD tests
├── test_notebook_ops.py        # Cell manipulation tests
├── test_utils.py               # Output sanitization tests
├── test_environment.py         # Environment detection tests
├── test_security_fixes.py      # Security validation tests
├── test_real_world.py          # Integration tests (optional)
├── test_async_integration.py   # Async execution tests (optional)
└── test_*.py                   # Other test files
```

### Test Categories

#### 1. Core Tests (109 tests)
- **No external dependencies** (no matplotlib/pandas required)
- **Fast** (~45s with pytest -n 4)
- **Run on every PR**

```bash
pytest tests/ -m "not optional" -n 4
```

#### 2. Optional Tests (5 tests)
- **Require matplotlib/pandas**
- **Heavy integration tests**
- **Run manually or in CI with full environment**

```bash
pytest -m optional
```

### Writing Tests

#### Test Naming Convention
```python
def test_<functionality>_<scenario>():
    # Example:
    def test_execute_cell_returns_output():
    def test_execute_cell_handles_error():
    def test_execute_cell_with_timeout():
```

#### Using Fixtures
```python
@pytest.mark.asyncio
async def test_start_kernel(tmp_path, create_test_notebook):
    # Fixtures from conftest.py
    nb_path = create_test_notebook("test.ipynb")
    manager = SessionManager()
    
    result = await manager.start_kernel(str(nb_path))
    
    assert "Kernel started" in result
    await manager.shutdown_all()
```

#### Marking Optional Tests
```python
@pytest.mark.asyncio
@pytest.mark.optional
async def test_matplotlib_plotting(tmp_path):
    """
    Test that requires matplotlib.
    
    Note: Marked as 'optional' - run with: pytest -m optional
    """
    import matplotlib.pyplot as plt  # Will skip if not available
    # ... test code
```

### Test Requirements

**Every new feature MUST include**:
1. Unit tests for core functionality
2. Integration test if it involves multiple components
3. Edge case tests (empty input, invalid input, etc.)
4. Error handling tests

**Tests MUST**:
- Pass locally before creating PR
- Have clear assertions with descriptive messages
- Clean up resources (kernels, temp files)
- Not depend on external services (unless marked optional)

---

## ➕ Adding New Features

### Adding a New MCP Tool

**Example**: Adding a `rename_notebook` tool

#### Step 1: Implement Core Logic (if needed)

Add to `notebook.py`:
```python
def rename_notebook(old_path: str, new_path: str) -> str:
    """
    Rename a notebook file.
    
    Args:
        old_path: Current path to notebook
        new_path: New path for notebook
    
    Returns:
        Success message
    
    Raises:
        FileNotFoundError: If old_path doesn't exist
        FileExistsError: If new_path already exists
    """
    old_path_obj = Path(old_path)
    new_path_obj = Path(new_path)
    
    if not old_path_obj.exists():
        raise FileNotFoundError(f"Notebook not found: {old_path}")
    if new_path_obj.exists():
        raise FileExistsError(f"Destination already exists: {new_path}")
    
    old_path_obj.rename(new_path_obj)
    return f"Notebook renamed: {old_path} → {new_path}"
```

#### Step 2: Register MCP Tool

Add to `main.py`:
```python
@server.call_tool()
async def rename_notebook(arguments: dict) -> list[TextContent]:
    """
    Rename a notebook file.
    
    Args:
        old_path (str): Current path to notebook
        new_path (str): New path for notebook
    """
    try:
        old_path = arguments.get("old_path")
        new_path = arguments.get("new_path")
        
        if not old_path or not new_path:
            raise ValueError("Both old_path and new_path required")
        
        result = notebook.rename_notebook(old_path, new_path)
        return [TextContent(type="text", text=result)]
    
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]
```

#### Step 3: Add Tests

Add to `tests/test_notebook.py`:
```python
def test_rename_notebook_success(tmp_path, create_test_notebook):
    """Test successful notebook rename."""
    old_path = create_test_notebook("old.ipynb")
    new_path = str(tmp_path / "new.ipynb")
    
    result = notebook.rename_notebook(old_path, new_path)
    
    assert "renamed" in result.lower()
    assert not Path(old_path).exists()
    assert Path(new_path).exists()


def test_rename_notebook_not_found(tmp_path):
    """Test rename with non-existent source."""
    with pytest.raises(FileNotFoundError):
        notebook.rename_notebook("nonexistent.ipynb", "new.ipynb")


def test_rename_notebook_destination_exists(tmp_path, create_test_notebook):
    """Test rename when destination already exists."""
    old_path = create_test_notebook("old.ipynb")
    new_path = create_test_notebook("new.ipynb")  # Already exists
    
    with pytest.raises(FileExistsError):
        notebook.rename_notebook(old_path, new_path)
```

#### Step 4: Update Documentation

Add to `MCP_JUPYTER_TOOLS_REFERENCE.md`:
```markdown
### `rename_notebook(old_path: str, new_path: str)`
Rename a notebook file.

**Example**:
\`\`\`python
rename_notebook("analysis.ipynb", "final_analysis.ipynb")
# Returns: "Notebook renamed: analysis.ipynb → final_analysis.ipynb"
\`\`\`

**Errors**:
- `FileNotFoundError`: Source notebook doesn't exist
- `FileExistsError`: Destination already exists
```

#### Step 5: Run Tests
```bash
pytest tests/test_notebook.py::test_rename_notebook_success -v
pytest tests/ -m "not optional" -n 4  # Ensure no regressions
```

---

## 🔄 Pull Request Process

### Before Creating PR

1. ✅ All tests pass: `pytest tests/ -m "not optional" -n 4`
2. ✅ Code formatted: `black src/ tests/`
3. ✅ No linter errors (if using flake8/pylint)
4. ✅ Documentation updated (if needed)
5. ✅ Commit messages follow convention

### Commit Message Convention

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Adding or updating tests
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `chore`: Build process or auxiliary tool changes

**Examples**:
```
feat(session): add streaming execution support

Implements real-time output streaming for long-running cells.
- Adds stream_execution() method to SessionManager
- Updates IOPub listener to support streaming
- Adds integration tests

Closes #42
```

```
fix(utils): prevent context overflow for large DataFrames

- Increase HTML table size threshold to 10 rows × 10 cols
- Add test for 100-row DataFrame handling
- Update documentation with new limits

Fixes #38
```

### PR Template

```markdown
## Description
Clear description of what this PR does and why.

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that causes existing functionality to not work as expected)
- [ ] Documentation update

## Testing
Describe the tests you ran:
- [ ] All existing tests pass
- [ ] Added new tests for this feature
- [ ] Manual testing performed (describe)

## Checklist
- [ ] Code follows project style guidelines (Black formatted)
- [ ] Self-review of code completed
- [ ] Comments added for complex logic
- [ ] Documentation updated
- [ ] No new warnings introduced
- [ ] Tests added/updated and passing
```

### Review Process

1. **Automated Checks**: CI/CD runs tests automatically
2. **Code Review**: Maintainer reviews code quality, design, tests
3. **Changes Requested**: Address feedback and push updates
4. **Approval**: Once approved, PR will be merged
5. **Merge**: Squash and merge into main branch

---

## 📚 Additional Resources

### Learning Resources
- [MCP Protocol Specification](https://github.com/anthropics/mcp)
- [Jupyter Client Documentation](https://jupyter-client.readthedocs.io/)
- [nbformat Documentation](https://nbformat.readthedocs.io/)
- [Black Code Style Guide](https://black.readthedocs.io/)
- [pytest Documentation](https://docs.pytest.org/)

### Project Documentation
- **[README.md](./README.md)**: Project overview and quick start
- **[MCP_JUPYTER_TOOLS_REFERENCE.md](./MCP_JUPYTER_TOOLS_REFERENCE.md)**: Complete API reference
- **[PRODUCTION_ROBUSTNESS.md](./PRODUCTION_ROBUSTNESS.md)**: Production features and architecture
- **[SECURITY_UX_UPDATE.md](./SECURITY_UX_UPDATE.md)**: Security fixes and updates

---

## 💬 Communication

### Asking Questions
- Check existing documentation first
- Search closed issues for similar questions
- Open new issue with clear description and context

### Reporting Bugs
Include:
1. Python version and OS
2. Steps to reproduce
3. Expected behavior
4. Actual behavior
5. Error messages/stack traces
6. Minimal reproducible example

### Suggesting Features
Include:
1. Use case / problem it solves
2. Proposed solution
3. Alternative solutions considered
4. Impact on existing functionality

---

## 🙏 Thank You!

Your contributions make this project better for everyone. We appreciate your time and effort!

For questions or clarifications, feel free to open an issue or reach out to the maintainers.

Happy coding! 🚀
