# Contributing to MCP Server Jupyter

Thank you for your interest in contributing! This document explains the architecture, development workflow, and how to maintain code quality.

## Table of Contents

1. [Development Setup](#development-setup)
2. [Architecture Overview](#architecture-overview)
3. [Code Organization](#code-organization)
4. [Component Deep Dives](#component-deep-dives)
5. [Adding New Features](#adding-new-features)
6. [Testing Strategy](#testing-strategy)
7. [Common Patterns](#common-patterns)
8. [Debugging Guide](#debugging-guide)
9. [Performance Considerations](#performance-considerations)
10. [Security Checklist](#security-checklist)

---

## Development Setup

### Prerequisites

- Python 3.10+
- Node.js 16+
- Git

### Server-Side Setup

```bash
# Clone the repo
git clone https://github.com/your-org/mcp-server-jupyter.git
cd mcp-server-jupyter/tools/mcp-server-jupyter

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e .

# Optional: Install optional dependencies
pip install dill pytest pytest-asyncio

# Run tests
pytest tests/
```

### Client-Side Setup (VS Code Extension)

The extension contains **Integration Tests** that spawn the real Python server in a VS Code Extension Host environment.

```bash
cd vscode-extension
npm install
npm run compile

# Run the Integration Test Suite (This launches a VS Code window for E2E testing)
npm test
```

> **Note**: These tests require a valid Python environment with `fastmcp` installed. The test harness attempts to locate `.venv` in the project root.

### Running Locally

**Start the server in debug mode:**

```bash
cd tools/mcp-server-jupyter
python -m src.main
```

**In VS Code:**
- Open the extension in VS Code: `code --extensionDevelopmentPath=. .`
- This launches a second VS Code window with the extension loaded.
- Open a test notebook and try executing cells.

---

## Architecture Overview

The system is divided into **Two Realms** that communicate via MCP (Model Context Protocol):

```
┌─────────────────────┐                    ┌────────────────────┐
│  VS CODE EXTENSION  │  ◄─────MCP────►  │   JUPYTER KERNEL   │
│  (TypeScript/Node)  │   (JSON-RPC)      │    (Python)        │
└─────────────────────┘                    └────────────────────┘
       Buffer Truth                         State Truth
```

### Core Invariants (Never Break These)

1. **Buffer is the Source of Truth for Code**: 
   - `run_cell_async(code_override)` must use the buffer content, not disk.
   - If you find yourself reading `notebook.ipynb` from disk in execution paths, that's a bug.

2. **State is Local to the Kernel**:
   - The kernel's heap is the only source of truth for variable state.
   - Reaper subsystem automatically recovers crashed kernels, preserving notebook structure.

3. **Edits are Proposals, Not Writes**:
   - `propose_edit()` returns JSON; it does NOT write to `notebook.ipynb`.
   - The client decides when to apply via `vscode.WorkspaceEdit`.

4. **Structure is Buffer-Injected**:
   - `get_notebook_outline()` must receive `structure_override` from the client.
   - Never rely on disk state for cell indices.

5. **Errors are Diagnostic, Not Opaque**:
   - When kernel operations fail, report *which operation* failed with context.
   - When sync is needed, explain *why* (cells without metadata, file modified, etc.).

---

## Code Organization

```
tools/mcp-server-jupyter/
├── src/
│   ├── main.py                 # FastMCP tool definitions (the API surface)
│   ├── session.py              # SessionManager: kernel lifecycle + execution
│   ├── notebook.py             # NotebookOps: file I/O, outline, edits
│   ├── notebook_ops.py         # Cell-level operations (read_cell_smart, search)
│   ├── utils.py                # Utilities (sanitize_outputs, inspect_variable)
│   ├── environment.py          # Env detection (conda, venv, system)
│   ├── git_tools.py            # Git integration (future)
│   ├── provenance.py           # Execution tracing (mcp_trace metadata)
│   ├── cell_id_manager.py      # Stable cell IDs (git-safe)
│   └── asset_manager.py        # Binary asset extraction
├── tests/
│   ├── conftest.py             # Pytest fixtures
│   ├── test_notebook_ops.py    # Notebook CRUD tests
│   ├── test_session_mock.py    # Session management tests
│   ├── test_execution.py       # Execution + streaming tests
│   └── test_async_integration.py # End-to-end async tests
└── pyproject.toml

vscode-extension/
├── src/
│   ├── extension.ts            # Entry point
│   ├── mcpClient.ts            # MCP protocol + argument injection
│   ├── notebookController.ts   # VS Code Notebook Controller
│   ├── types.ts                # Type definitions
│   └── dependencies.ts         # Environment detection
├── test/
│   └── suite/                  # VS Code extension tests
└── package.json
```

### Key Files by Purpose

| File | Responsibility |
|------|-----------------|
| `main.py` | **MCP API Surface**: Every `@mcp.tool()` here is a contract with clients. Changes require tests. |
| `session.py` | **Kernel Lifecycle**: Manages kernel processes, execution queues, async streams. Most complex. |
| `mcpClient.ts` | **Argument Injection**: Intercepts tool calls to inject buffer structure. Critical for buffer-awareness. |
| `notebookController.ts` | **VS Code Integration**: Handles UI events, streaming outputs, edit application. |
| `notebook.py` | **File I/O**: Reads/writes `notebook.ipynb`. Should only be called for metadata updates, not execution. |
| `utils.py` | **Sanitization**: Converts kernel outputs to agent-consumable format. MIME handling is here. |

---

## Component Deep Dives

### 1. Session Manager (`session.py`)

**Purpose**: Manages the kernel process and execution queue.

**Lifecycle**:
```python
SessionManager
├── start_kernel()
│   ├── Spawn kernel process (jupyter_client.AsyncKernelManager)
│   ├── Start I/O listener (async)
│   └── Store in sessions[notebook_path]
│
├── execute_cell_async(code)
│   ├── Queue execution with UUID
│   ├── Return execution ID immediately
│   └── Process queue in background
│
└── stop_kernel()
    └── Kill process + cleanup
```

**Key Methods**:

- `execute_cell_async(nb_path, index, code)`: 
  - Queues code for execution
  - Returns UUID immediately (non-blocking)
  - Must respect `stop_on_error` flag

- `_kernel_listener()`:
  - Async loop that reads from kernel's iopub channel
  - Routes outputs to execution data
  - Updates execution status

- `execute_cell_async(nb_path, cell_index, code_override)`:
  - Executes code in kernel with buffer override support
  - Streams outputs via polling (no SSE)
  - Persists cell IDs atomically for git-safe workflows

**Testing Patterns**:
```python
# test_session_mock.py
@pytest.fixture
async def mock_session():
    sm = SessionManager()
    # Mock kernel with canned responses
    yield sm
    # Cleanup

@pytest.mark.asyncio
async def test_execute_cell_async_returns_task_id(mock_session):
    task_id = await mock_session.execute_cell_async(path, 0, "x=1")
    assert task_id is not None
    assert isinstance(task_id, str)
```

### 2. Notebook Operations (`notebook.py`)

**Purpose**: Filesystem and metadata operations.

**Key Functions**:

- `get_notebook_outline(path)`: 
  - Reads from disk
  - Returns cell list with previews
  - Called via `get_notebook_outline(path, structure_override=...)`
  - If `structure_override` is provided, **use it** (buffer wins)

- `format_outline(structure_override)`:
  - Formats buffer structure for consistency
  - Handles both nbformat and VSCode cell schemas

- `append_cell(path, content, type)`:
  - Adds cell to end
  - Must clear outputs
  - Atomic write

- `propose_edit(index, new_content)`:
  - Returns JSON proposal (no disk write!)
  - Includes `_mcp_action: "apply_edit"` signal

**Testing Patterns**:
```python
def test_append_cell_clears_output(tmp_path):
    nb_path = tmp_path / "test.ipynb"
    append_cell(str(nb_path), "print('hi')", "code")
    
    nb = nbformat.read(nb_path, as_version=4)
    assert len(nb.cells) == 1
    assert nb.cells[0].outputs == []  # Must be empty

def test_format_outline_handles_buffer_structure():
    struct = [
        {"cell_type": "code", "source": "x=1", "id": "abc"},
        {"kind": "markdown", "source": "# Title", "id": "def"}  # VSCode format
    ]
    outline = format_outline(struct)
    assert outline[0]["type"] == "code"
    assert outline[1]["type"] == "markdown"  # Normalized
```

### 3. MCP Client (`mcpClient.ts`)

**Purpose**: JSON-RPC communication with server + argument injection.

**Key Methods**:

- `callTool(toolName, args)`:
  - **INTERCEPTION POINT**: Before sending to server
  - If `toolName === 'get_notebook_outline'`:
    - Read `vscode.notebookDocuments`
    - Build `structure_override` from cells
    - Inject into args
  - If `toolName === 'run_cell_async'`:
    - Code is already in args (from `executeCell`)
    - No modification needed

- `handleResponse(response)`:
  - Check for `_mcp_action: "apply_edit"`
  - Call `handleApplyEdit()` if present

- `handleApplyEdit(proposal)`:
  - Extract `index` and `new_content`
  - Create `vscode.WorkspaceEdit`
  - Apply to cell document

**Testing Patterns**:
```typescript
describe('mcpClient Argument Injection', () => {
  it('should inject structure_override into get_notebook_outline', async () => {
    const mockNotebook = createMockNotebook([
      { kind: 'code', text: 'x=1' },
      { kind: 'markup', text: '# Title' }
    ]);
    
    // Mock vscode.notebookDocuments
    const result = await client.callTool('get_notebook_outline', {
      notebook_path: '/path/to/notebook.ipynb'
    });
    
    // Verify request sent includes structure_override
    expect(lastRequest.params.arguments.structure_override).toBeDefined();
    expect(lastRequest.params.arguments.structure_override.length).toBe(2);
  });
});
```

### 4. Execution Stream (`get_execution_stream`)

**Data Flow**:
```
Kernel Output (stdout, stderr, display_data, error)
    ↓
session.py: _kernel_listener collects in execution['outputs']
    ↓
main.py: get_execution_stream() fetches new outputs since last poll
    ↓
utils.py: sanitize_outputs() returns {"llm_summary": "...", "raw_outputs": [...]}
    ↓
mcpClient.ts: Detects {"llm_summary": "...", "raw_outputs": [...]}
    ↓
notebookController.ts: For each raw_output:
    - If application/vnd.plotly.v1+json: render as Plotly
    - If text/plain: render as text
    - If image/*: render as image
```

**Key Invariant**: `sanitize_outputs` returns JSON with both LLM context AND raw MIME types. The LLM sees text; the human sees rich media.

---

## Adding New Features

### Feature Type 1: New Execution Tool

**Example**: Add `get_available_imports()` tool to list installed packages.

**Steps**:

1. **Add to `main.py`**:
```python
@mcp.tool()
def get_available_imports() -> str:
    """List installed packages in the kernel's environment."""
    code = """
import pkg_resources
pkgs = [d.project_name for d in pkg_resources.working_set]
print(json.dumps(pkgs))
"""
    # Execute in kernel, capture output
    return await session_manager.run_simple_code(notebook_path, code)
```

2. **Add tests** in `tests/test_notebook_ops.py`:
```python
@pytest.mark.asyncio
async def test_get_available_imports():
    result = await main.get_available_imports(notebook_path)
    pkgs = json.loads(result)
    assert isinstance(pkgs, list)
    assert 'jupyter' in pkgs  # Should be present
    assert all(isinstance(p, str) for p in pkgs)
```

3. **Document in `README.md`** API Reference section.

### Feature Type 2: New Client-Side Interception

**Example**: Inject environment info when `start_kernel` is called.

**Steps**:

1. **Update `mcpClient.ts`**:
```typescript
private async callTool(toolName: string, args: Record<string, any>): Promise<any> {
    // ... existing get_notebook_outline injection ...
    
    // NEW: Inject environment info
    if (toolName === 'start_kernel' && !args.env_info) {
        args.env_info = {
            platform: process.platform,
            node_version: process.version,
            extension_version: '1.0.0'
        };
    }
    
    // ... rest of callTool ...
}
```

2. **Update `main.py` signature**:
```python
@mcp.tool()
async def start_kernel(notebook_path: str, venv_path: str = "", env_info: Optional[dict] = None):
    # env_info now available
    logger.info(f"Starting kernel on {env_info.get('platform')}")
    return await session_manager.start_kernel(notebook_path, venv_path)
```

3. **Add tests**:
```typescript
// test/suite/mcpClient.test.ts
it('should inject env_info into start_kernel call', async () => {
    const request = await captureToolCall('start_kernel', {});
    expect(request.params.arguments.env_info).toBeDefined();
    expect(request.params.arguments.env_info.platform).toBe(process.platform);
});
```

### Feature Type 3: New Kernel Inspection Tool

**Example**: Add `get_memory_usage(notebook_path)` to report kernel memory consumption.

**Steps**:

1. **Add to `session.py`**:
```python
async def get_memory_usage(self, notebook_path: str) -> Dict[str, Any]:
    """Get memory usage of kernel variables."""
    session = self.sessions.get(str(Path(notebook_path).resolve()))
    if not session:
        return {"error": "No session"}
    
    code = """
import sys
import gc
gc.collect()
vars_memory = {k: sys.getsizeof(v) for k, v in globals().items() if not k.startswith('_')}
total_mb = sum(vars_memory.values()) / (1024**2)
print(f"Total memory: {total_mb:.2f} MB")
print(f"Top variables: {sorted(vars_memory.items(), key=lambda x: -x[1])[:5]}")
"""
    result = await self.execute_cell_async(notebook_path, -1, code)
    return result
```

2. **Add to `main.py`**:
```python
@mcp.tool()
async def get_memory_usage(notebook_path: str):
    """Get memory usage of kernel variables."""
    return await session_manager.get_memory_usage(notebook_path)
```

3. **Add tests**:
```python
@pytest.mark.asyncio
async def test_get_memory_usage():
    # Set up kernel state with large data
    await session.execute_cell_async(path, 0, "import numpy as np; x = np.zeros((1000, 1000))")
    
    # Get memory usage
    result = await session.get_memory_usage(path)
    assert "Total memory" in result["output"]
    assert "x" in result["output"]  # Should show x as top variable
```

---

## Testing Strategy

### Test Pyramid

```
                 /\
               /  \  E2E Tests
              /────\ (notebookController.ts orchestration)
            /      \
          /────────\  Integration Tests
        /  session + notebook ops (async)
      /──────────────\
    / Unit Tests     \
  /──────────────────\ (utils, notebook.py, cell_id_manager)
/──────────────────────\
```

### Running Tests

**Server Tests**:
```bash
cd tools/mcp-server-jupyter
pytest tests/                           # All
pytest tests/test_notebook_ops.py       # Specific file
pytest tests/ -k "test_append_cell"     # Specific test
pytest tests/ -v                        # Verbose
pytest tests/ --cov=src                 # Coverage report
```

**Client Tests**:
```bash
cd vscode-extension
npm test
npm run test:watch
npm run test:coverage
```

### Writing Tests

**Principle**: Every tool added requires a test. No exceptions.

**Test Checklist for New Tool**:

- [ ] **Happy Path**: Tool succeeds with valid inputs
- [ ] **Error Handling**: Tool fails gracefully with invalid inputs
- [ ] **Async Behavior**: If async, verify task IDs, polling, completion
- [ ] **Side Effects**: Verify files created, kernel state changed (or not)
- [ ] **Documentation**: Docstring with Args/Returns/Raises

**Example Test Template**:

```python
@pytest.mark.asyncio
async def test_my_new_tool():
    """Test that my_new_tool does X."""
    # Setup
    nb_path = tmp_path / "test.ipynb"
    create_test_notebook(nb_path)
    sm = SessionManager()
    await sm.start_kernel(str(nb_path))
    
    # Execute
    result = await session_manager.my_new_tool(str(nb_path), arg1="value1")
    
    # Verify
    assert "success" in result.lower()
    
    # Cleanup
    await sm.stop_kernel(str(nb_path))

def test_my_new_tool_rejects_invalid_input():
    """Test that my_new_tool validates inputs."""
    with pytest.raises(ValueError):
        my_new_tool(None, arg1="")  # None is invalid
```

---

## Common Patterns

### Pattern 1: Executing Python Code in Kernel

**Don't do this**:
```python
# WRONG: Reads from disk
cell = notebook.read_cell(path, 0)
await session.execute_cell_async(path, 0, cell['source'])
```

**Do this**:
```python
# RIGHT: Code is passed in (from buffer)
await session.execute_cell_async(path, 0, code_override)
```

### Pattern 2: Returning Structured Data

**Don't do this**:
```python
# WRONG: Returns string
return "Cell 0: import pandas\nCell 1: df = pd.read_csv(...)"
```

**Do this**:
```python
# RIGHT: Returns JSON
return json.dumps({
    "cells": [
        {"index": 0, "type": "code", "source_preview": "import pandas..."},
        {"index": 1, "type": "code", "source_preview": "df = pd.read_csv(...)"}
    ]
})
```

### Pattern 3: Graceful Degradation

**Don't do this**:
```python
# WRONG: Crashes if dill not installed
import dill
dill.dump_session(f)
```

**Do this**:
```python
# RIGHT: Diagnoses the problem
code = """
try:
    import pandas as pd
    result = df.merge(other_df)
    print(f"Merged {len(result)} rows")
except NameError as e:
    print(f"ERROR: Variable not defined: {e}")
    print(f"Available variables: {[k for k in dir() if not k.startswith('_')]}")
except Exception as e:
    print(f"EXECUTION FAILED: {e}")
    import traceback
    traceback.print_exc()
"""
await session.execute_cell_async(path, -1, code)
```

### Pattern 4: Client-Side State Injection

**In mcpClient.ts**:
```typescript
// CORRECT: Check for null structure_override and inject
if (toolName === 'get_notebook_outline' && !args.structure_override) {
    const nbDoc = vscode.workspace.notebookDocuments.find(
        nb => nb.uri.fsPath === vscode.Uri.file(args.notebook_path).fsPath
    );
    if (nbDoc) {
        args.structure_override = nbDoc.getCells().map((cell, idx) => ({
            index: idx,
            source: cell.document.getText(),
            cell_type: cell.kind === vscode.NotebookCellKind.Code ? 'code' : 'markdown'
        }));
    }
}
```

---

## Debugging Guide

### Enable Verbose Logging

**Server**:
```bash
LOGLEVEL=DEBUG python -m src.main
```

**Client**:
```typescript
// In mcpClient.ts
private handleStdout(data: Buffer) {
    console.log('[MCP Stdout]', data.toString());  // Add this
    // ... existing logic ...
}
```

### Common Issues

| Issue | Symptom | Root Cause | Fix |
|-------|---------|-----------|-----|
| Agent executes wrong cell | Agent runs Cell 0 but it's actually Cell 1 | Structure not injected | Check `mcpClient.ts` interception in `callTool` |
| Edit doesn't appear | `propose_edit` tool returns OK but code doesn't change | Client not intercepting `_mcp_action` | Check `handleResponse` in `mcpClient.ts` |
| Cell execution hangs | `execute_cell` never returns | Kernel deadlock or infinite loop | Check kernel logs: `~/.jupyter/jupyter_kernel_*.log`, Reaper will auto-restart after timeout |
| Kernel exits unexpectedly | Execution stops, kernel process gone | Process crash or OOM | Check kernel logs: `~/.jupyter/jupyter_kernel_*.log` |
| Polling lags | Outputs appear slowly | Polling interval too long | Reduce `pollingInterval` in config |

### Inspecting Kernel State

```python
# From agent code
result = inspect_variable("my_dataframe")
print(result)
# Output:
# ### Type: DataFrame
# - Shape: (1000, 50)
# - Memory: 4.2 MB
# - Columns: ['col1', 'col2', ...]
```

### Capturing MCP Traffic

```bash
# Capture raw JSON-RPC to file
strace -e write -s 500 python -m src.main 2>&1 | grep -E '^\{' > mcp_traffic.log
```

---

## Performance Considerations

### 1. Polling Latency (500ms default)

**Problem**: 500ms delay between output and display.  
**Solution Options**:
- Reduce interval (costs more CPU)
- Implement WebSocket push (major refactor)
- Batch outputs (collect 100ms of output, send once)

**Benchmark**:
```python
# Time get_execution_stream call
import time
start = time.time()
stream = await mcpClient.getExecutionStream(path, task_id)
elapsed = time.time() - start
print(f"Polling latency: {elapsed*1000:.1f}ms")
```

### 2. Large Output Handling

**Problem**: Large outputs (>100MB) cause memory pressure.  
**Solution**:
- Outputs >10MB are automatically offloaded to `/assets` directory
- Truncation applied at 100MB
- Delete unused dataframes: `del df_old`
- Profile with: `import sys; sys.getsizeof(my_var)`

### 3. Kernel Startup Time

**Problem**: Starting kernel takes 5-10 seconds.  
**Solution**:
- Keep one kernel running (don't start/stop repeatedly)
- Use pre-warmed environments (conda env with common packages pre-installed)

---

## Security Checklist

**Before merging a PR**, ensure:

- [ ] **No Disk Reads During Execution**: Code comes from buffer, not disk
- [ ] **No `eval()` or `exec()` on User Input**: Use `code_override` only for buffer content
- [ ] **Safe Variable Inspection**: `inspect_variable` avoids `str(obj)` on unknown types
- [ ] **Path Traversal Protection**: Validate `MCP_ALLOWED_ROOT` restrictions
- [ ] **Error Messages are Safe**: Don't leak secrets in tracebacks
- [ ] **Test with Malicious Input**: Try SQLi, path traversal, etc.

**Example Security Test**:
```python
def test_inspect_variable_safe_with_malicious_repr():
    """Ensure inspect_variable doesn't execute arbitrary code."""
    code = """
class Bomb:
    def __str__(self):
        import os
        os.system("rm -rf /")  # DON'T ACTUALLY DO THIS
        return "Boom"

b = Bomb()
"""
    # Run code in kernel (safely, in test env)
    # inspect_variable should NOT call str(b)
    result = inspect_variable(path, "b")
    assert "Bomb" in result
    assert "Boom" not in result  # __str__ was not called
```

---

## Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(session): add get_memory_usage tool
- Allows agents to inspect kernel memory consumption
- Includes variable-level breakdown
- Fixes #42

fix(mcpClient): correct structure_override injection logic
- Was not being injected on first call
- Added test case

test(notebook_ops): increase coverage to 95%

docs(README): add kernel recovery troubleshooting section
```

---

## PR Checklist

Before submitting a PR:

- [ ] Tests pass: `pytest tests/ && npm test`
- [ ] Code style: `black src/`, `eslint src/`
- [ ] Coverage maintained: `pytest --cov=src`
- [ ] Documentation updated: README.md or inline docstrings
- [ ] No breaking changes to API (or documented)
- [ ] Security review done
- [ ] One concern per PR (don't mix features)

---

## Resources

- **MCP Spec**: [modelcontextprotocol.io](https://modelcontextprotocol.io/)
- **Jupyter Kernel**: [jupyter-client docs](https://jupyter-client.readthedocs.io/)
- **VS Code API**: [code.visualstudio.com/api](https://code.visualstudio.com/api)
- **NBFormat**: [nbformat.readthedocs.io](https://nbformat.readthedocs.io/)
- **Dill Docs**: [dill.readthedocs.io](https://dill.readthedocs.io/)

---

## Getting Help

- **Architecture Questions**: See [ARCHITECTURE_REMEDIATION.md](ARCHITECTURE_REMEDIATION.md)
- **API Reference**: See [README.md](README.md)
- **Issues**: Open a GitHub issue with `[debug-info]` label
- **Discussions**: Start a discussion in GitHub Discussions

---

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.

Thank you for helping make collaborative AI notebooks a reality! 🚀
