# MCP Server Jupyter

**Stateful, Production-Ready Jupyter Notebook Execution via Model Context Protocol**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-120%20passing-success)](./tests/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## 🎯 What is This?

An MCP (Model Context Protocol) server that transforms Jupyter notebooks into a **reliable backend API** for AI agents. Execute cells, manipulate notebooks, manage kernels, and inspect variables—all through stateful, production-grade MCP tools.

**Perfect for**: AI agents performing data analysis, scientific computing, visualization, or any Jupyter-based workflow.

---

## ✨ Key Features

### 🔒 Production-Ready
- **Security**: Safe variable inspection (no `eval()`), sandboxed execution via Docker
- **Robustness**: Automatic kernel recovery, execution provenance tracking, clear_output handling, **execution timeouts**
- **Context-Aware**: Smart HTML table preview (reduces API calls by 50%)
- **Asset Management**: Automatic extraction of plots/PDFs to disk (98% context reduction)
- **Asset-Based Output Storage**: Large text outputs (>2KB or >50 lines) offloaded to `assets/text_*.txt` files, preventing VS Code crashes and context overflow ⭐ **NEW**
- **Progress Bar Support**: Handles `clear_output` messages correctly (prevents file size explosion)

### 🚀 Performance
- **Asynchronous Execution**: Non-blocking cell execution with status tracking
- **Auto-reload**: Code changes detected automatically (no kernel restarts)
- **Parallel Testing**: pytest-xdist support for fast test execution
- **Environment Detection**: Robust `conda activate` / `venv` simulation for complex ML environments

### 🛠️ Comprehensive API
- **29 MCP Tools** covering every notebook operation
- **Handoff Protocol**: Sync kernel state after human edits (for VS Code extensions)
- **Agent Observability**: Real-time streaming feedback for long-running cells
- **Resource Monitoring**: CPU/RAM tracking for auto-restart logic
- **Full CRUD**: Create, read, update, delete cells and notebooks
- **Metadata Management**: Provenance tracking, custom metadata, kernel info
- **Variable Inspection**: Human-readable summaries of DataFrames, lists, dicts

---

## 📦 Installation

### Requirements
- **Python**: 3.10, 3.11, or 3.12
- **OS**: Windows, macOS, Linux
- **Dependencies**: Jupyter Client, nbformat, ipykernel, MCP SDK, psutil

### Setup

1.  **Clone and Install**:
    ```bash
    git clone https://github.com/yourusername/mcp-server-jupyter.git
    cd mcp-server-jupyter
    pip install -e tools/mcp-server-jupyter
    ```

---

## 🏗️ Architecture: The "Hub and Spoke" Model

To enable collaboration between an AI Agent and a Human (typing in VS Code), both must share the **same** running Jupyter kernel. We achieve this using a "Hub and Spoke" architecture:

1.  **The Hub (Server)**: A single `mcp-jupyter` process running in the background (e.g., in `tmux`) acting as the source of truth for kernel state.
2.  **Spoke 1 (VS Code)**: The editor connects via WebSocket to visualize results and allow human edits.
3.  **Spoke 2 (Agent)**: The AI connects via a "Bridge" mode to execute code and analyze data.

### 🚀 Quick Start

#### 1. Start the "Hub" (Server)
Run this in a dedicated terminal (or `tmux`/`screen` session):

```bash
# Start the server on port 3000
mcp-jupyter --transport websocket --port 3000
```
*   **Windows**: Use a dedicated Command Prompt or PowerShell window.
*   **Linux/Mac**: Use `tmux new -s jupyter` or `screen -S jupyter` to keep it running in the background.

#### 2. Connect Your Agent (Spoke 1)
Configure your MCP client (like Claude Desktop or Copilot) with `mcp.json`. This tells the agent to connect to your running server instead of starting a new one.

**`mcp.json` Configuration**:
```json
{
  "mcpServers": {
    "jupyter": {
      "command": "mcp-jupyter",
      "args": [
        "--mode", "client",
        "--port", "3000"
      ]
    }
  }
}
```

#### 3. Connect VS Code (Spoke 2)
1.  Install the **MCP Jupyter** VS Code extension.
2.  Open Settings (`Ctrl+,`) and search for `mcp-jupyter`.
3.  Set **Server Mode** to `connect`.
4.  Set **Remote Port** to `3000`.
5.  Run **Developer: Reload Window** to apply changes.

Now, when you define a variable in VS Code (`x = 42`), the Agent can immediately see it (`inspect_variable('x')`), and vice versa.

---

## 💻 Windows Setup

Windows requires slightly different handling for paths and background processes.

1.  **Start the Hub**:
    Open PowerShell or Command Prompt and run:
    ```powershell
    mcp-jupyter --transport websocket --port 3000
    ```
    *Keep this window open.*

2.  **`mcp.json` for Windows**:
    You must use double backslashes for paths in JSON.
    ```json
    {
      "mcpServers": {
        "jupyter": {
          "command": "mcp-jupyter.exe", 
          "args": [
            "--mode", "client",
            "--port", "3000"
          ]
        }
      }
    }
    ```
    *Note: If `mcp-jupyter` is not in your PATH, provide the full path to the executable script in your python scripts folder (e.g., `C:\\Users\\You\\AppData\\Roaming\\Python\\Scripts\\mcp-jupyter.exe`).*

---

## 🤖 The "Jupyter Expert" Agent

The file [.github/agents/Jupyter Expert.agent.md](../../.github/agents/Jupyter%20Expert.agent.md) is a **System Prompt** designed to turn a generic LLM into a specialized Data Science assistant.

### How it Works
When you load this agent definition (e.g., in GitHub Copilot or a custom Agent UI), it instructs the model to:
1.  **Respect the Disk**: Checks `detect_sync_needed` before execution to prevent overwriting user edits.
2.  **Use Stable IDs**: Always calls `get_notebook_outline` to get valid Cell IDs before editing.
3.  **Sync State**: Automatically runs `sync_state_from_disk` if it detects you changed the code.

To use it, copy the content of that file into your Custom Instructions or System Prompt configuration.


- **Optional**: kaleido (for Plotly static PNG rendering), matplotlib, bokeh

### Quick Start

#### Option 1: Using Poetry (Recommended)
```bash
cd mcp-server-jupyter
poetry install
poetry shell
```

#### Option 2: Using pip
```bash
cd mcp-server-jupyter
pip install -e .
```

#### Option 3: Using uv (Fast)
```bash
cd mcp-server-jupyter
uv pip install -e .
```

### Verify Installation
```bash
pytest tests/ -m "not optional"  # Run core tests (109 tests, ~45s)
pytest tests/                     # Run all tests including heavy integration
```

---

## 🚀 Quick Start Guide

### 1. Start a Kernel
```python
# Via MCP tool
start_kernel("analysis.ipynb")
# Returns: "Kernel started (PID: 12345). CWD set to: /path/to/notebook"
```

### 2. Execute Code
```python
# Synchronous (blocks until complete)
execute_cell("analysis.ipynb", cell_index=0)

# Asynchronous (non-blocking)
exec_id = execute_cell_async("analysis.ipynb", cell_index=0, code="import pandas as pd")
status = get_execution_status("analysis.ipynb", exec_id)
# Returns: {"status": "completed", "output": "...", "cell_index": 0}
```

### 3. Monitor Long-Running Cells
```python
# Stream outputs from long-running execution
exec_id = execute_cell_async("analysis.ipynb", cell_index=0, code="train_model(epochs=100)")
output_idx = 0

while True:
    stream = json.loads(get_execution_stream("analysis.ipynb", exec_id, output_idx))
    
    if stream['new_outputs']:
        print(stream['new_outputs'])  # "Epoch 12/100... loss: 0.342"
        output_idx = stream['next_index']
    
    if stream['status'] in ['completed', 'error']:
        break
    
    time.sleep(5)  # Poll every 5 seconds
```

### 4. Check Kernel Resources
```python
# Monitor kernel CPU/RAM for auto-restart logic
resources = json.loads(check_kernel_resources("analysis.ipynb"))
if resources.get('memory_percent', 0) > 80:
    stop_kernel("analysis.ipynb")
    start_kernel("analysis.ipynb")
    print("Restarted kernel due to high memory usage")
```

### 5. Inspect Variables
```python
# Get human-readable summary
inspect_variable("analysis.ipynb", "df")
# Returns markdown with shape, columns, head for DataFrames
# or length, sample for lists/dicts
```

### 6. Manipulate Notebooks
```python
# Create new notebook
create_notebook("new_analysis.ipynb", initial_cells='[{"type": "code", "source": "import pandas"}]')

# Edit cells
edit_cell("analysis.ipynb", index=0, new_content="# Updated code")

# Organize cells
move_cell("analysis.ipynb", from_index=0, to_index=3)
merge_cells("analysis.ipynb", start_index=1, end_index=3)
```

---

## 📚 Tool Categories

### Core Operations (8 tools)
- `start_kernel()` - Start Jupyter kernel
- `list_kernels()` - List active sessions
- `stop_kernel()` - Stop kernel
- `execute_cell()` - Synchronous execution
- `execute_cell_async()` - Async execution
- `get_execution_status()` - Check async status
- `get_execution_stream()` - Stream outputs from running execution *(NEW)*
- `check_kernel_resources()` - Monitor kernel CPU/RAM usage *(NEW)*

### Handoff Protocol (2 tools) ⭐ NEW
- `detect_sync_needed()` - Check if kernel state is out of sync with disk
- `sync_state_from_disk()` - Re-execute cells to rebuild kernel state after human edits
> **Use Case**: When building a VS Code extension or UI on top of this server, these tools solve the "Split Brain" problem where the agent's kernel state diverges from disk after human intervention. See [Handoff Protocol](#-handoff-protocol) below for details.

### Notebook Management (1 tool)
- `create_notebook()` - Create new notebooks with metadata

### Cell Manipulation (5 tools)
- `move_cell()` - Reorder cells
- `copy_cell()` - Duplicate cells
- `merge_cells()` - Combine multiple cells
- `split_cell()` - Split cell at line
- `change_cell_type()` - Convert code/markdown/raw

### CRUD Operations (4 tools)
- `insert_cell()` - Add new cells
- `edit_cell()` - Modify cell content
- `delete_cell()` - Remove cells
- `read_notebook()` - Get full notebook structure

### Metadata Operations (7 tools)
- `get_metadata()` / `set_metadata()` - Notebook-level metadata
- `get_cell_metadata()` / `set_cell_metadata()` - Cell-level metadata
- `delete_metadata()` / `delete_cell_metadata()` - Remove metadata
- `list_metadata_keys()` - List available keys

### Information & Inspection (3 tools)
- `list_variables()` - List all variables in kernel
- `get_variable_info()` - Get structured variable data
- `inspect_variable()` - Get human-readable summary

### Asset Management (2 tools) ⭐ **NEW**
- `read_asset()` - Read content from offloaded output files with pagination/search
- `prune_unused_assets()` - Garbage collect orphaned asset files (runs automatically on kernel stop)

> **Use Case**: When cells produce massive outputs (50MB training logs, large arrays), the system automatically offloads them to `assets/text_*.txt` files. Agents can use `read_asset()` to grep for errors or read specific line ranges without loading the entire output into context. Automatic cleanup prevents disk bloat.

---

## 🤝 Handoff Protocol

**Agent ↔ Human Workflow**

### Problem: The "Split Brain" Scenario

When building a VS Code extension (or any UI) on top of `mcp-server-jupyter`, you face a **fundamental architectural challenge**:

- **Agent Mode**: The MCP server's kernel has variables in RAM (`df = load_data()`)
- **Human Mode**: The user edits the notebook in VS Code with their own kernel
- **Switch Back to Agent**: The agent's kernel is OUT OF SYNC with disk changes

**Result**: `KeyError`, `NameError`, or stale variable state when agent resumes.

### Solution: The "Handoff Protocol"

Instead of trying to share kernel state (which causes race conditions), we implement a **clear handoff procedure**:

1. **Disk is Source of Truth** (not RAM)
2. **Agent is responsible for syncing** when resuming work
3. **Two new MCP tools** enforce this protocol

### New MCP Tools

#### 1. `detect_sync_needed(notebook_path: str)`

**Purpose**: Check if kernel state is out of sync with disk.

**Returns**:
```json
{
  "sync_needed": true,
  "reason": "Found 3 cells without agent metadata (likely human-added)",
  "human_cells": [5, 6, 7],
  "recommendation": "sync_state_from_disk",
  "suggested_strategy": "smart"
}
```

**When to Use**:
- Agent starts a new session
- Agent resumes work after human intervention
- Before executing code that depends on variables

#### 2. `sync_state_from_disk(notebook_path: str, strategy: str)`

**Purpose**: Re-execute cells from disk to rebuild kernel RAM state.

**Strategies**:
| Strategy | Behavior | Use When |
|----------|----------|----------|
| `"incremental"` | **(Recommended)** Finds the first "dirty" cell (content changed vs execution history) and re-runs from there. | Default. Maximizes performance while ensuring correctness. |
| `"full"` | Re-executes ALL code cells | Fallback if incremental fails or state is corrupted. |

### Agent Workflow (System Prompt Integration)

Add this to your agent's system prompt:

```markdown
## Handoff Protocol: Resuming Work After Human Edits

When you start a new session or resume work on a notebook:

1. **Always check sync status first**:
   ```python
   status = detect_sync_needed("analysis.ipynb")
   ```

2. **If sync_needed = true, run sync before proceeding**:
   ```python
   if status['sync_needed']:
       result = sync_state_from_disk("analysis.ipynb", strategy="smart")
       print(f"Synced {result['cells_synced']} cells to rebuild state")
   ```

3. **Now safe to continue work**:
   ```python
   append_cell("analysis.ipynb", "# Agent's new analysis code")
   ```

**Why This Matters**:
If you skip step 2, you'll get errors like:
- `KeyError: 'new_col'` (human added a column you never executed)
- `NameError: name 'df_clean' is not defined` (human renamed a variable)
```

### VS Code Extension Integration

**"Traffic Light" UI Pattern**

```typescript
// extension.ts

let agentMode = false; // false = Human Mode, true = Agent Mode

vscode.commands.registerCommand('jupyter.startAgentMode', async () => {
    // 1. Lock the editor
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        editor.options = { readOnly: true };
    }
    
    // 2. Check if sync needed
    const mcpResponse = await mcpClient.call('detect_sync_needed', {
        notebook_path: currentNotebookPath
    });
    
    if (mcpResponse.sync_needed) {
        // 3. Show progress notification
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Syncing kernel state with disk...",
        }, async () => {
            await mcpClient.call('sync_state_from_disk', {
                notebook_path: currentNotebookPath,
                strategy: 'smart'
            });
        });
    }
    
    // 4. Agent can now work
    agentMode = true;
    vscode.window.showInformationMessage('🤖 Agent Mode Active');
});
```

---

## 🔐 Security Features

### 1. Safe Variable Inspection
**Problem**: Previous versions used `eval(variable_name)` which allowed code injection.

**Solution**: Dictionary-based lookups prevent arbitrary code execution:
```python
# SAFE: Only looks up variable names
if variable_name in locals():
    obj = locals()[variable_name]
elif variable_name in globals():
    obj = globals()[variable_name]
else:
    return "Variable not found"
```

**Impact**: Prevents attacks like `inspect_variable(path, "__import__('os').system('rm -rf /')")`

### 2. Asset Extraction
Binary outputs (plots, PDFs) automatically saved to `assets/` directory:
- **Prevents context overflow**: 50KB images → 1KB file paths (98% reduction)
- **Deduplication**: Hash-based filenames avoid duplicate storage
- **Priority handling**: PDF > SVG > PNG > JPEG (only highest priority saved)

### 3. Execution Provenance
Every cell execution automatically tracked with metadata:
```json
{
  "execution_timestamp": "2024-01-15T14:30:00.123456",
  "kernel_env_name": "conda:data-science",
  "kernel_python_path": "/opt/conda/envs/data-science/bin/python",
  "agent_tool": "mcp-jupyter"
}
```

---

## ⚡ Performance Optimizations

### Asset-Based Output Storage ⭐ **NEW**
**Problem**: Large training logs (50MB+) crash VS Code UI and overflow agent context windows.

**Solution**: Text outputs >2KB or >50 lines are automatically offloaded to `assets/text_{hash}.txt`:

**Architecture**: "Stubbing & Paging"
```python
# Large output automatically intercepted
for epoch in range(1000):
    print(f"Epoch {epoch}: Loss {loss}")  # 50MB of text

# VS Code receives a stub instead:
"""
Epoch 1: Loss 0.99
Epoch 2: Loss 0.98
... [25 lines omitted] ...

>>> FULL OUTPUT (50.2MB, 1000 lines) SAVED TO: text_abc123def456.txt <<<
"""

# Agent can grep for errors without loading entire file
read_asset("assets/text_abc123def456.txt", search="error")
# Or read specific section
read_asset("assets/text_abc123def456.txt", lines=[900, 1000])
```

**Benefits**:
- **VS Code Stability**: No more UI crashes from 100MB logs
- **Agent Context**: Sees 20-line summary instead of 50,000 tokens
- **Git Hygiene**: `.ipynb` files stay small and diff-able (assets/ is auto-gitignored)
- **Auto-Cleanup**: Garbage collector removes orphaned files on kernel stop

**Impact**: 
- Context reduction: 50MB → 2KB (98%)
- Test coverage: 7 new tests in `tests/test_asset_offload.py`

### Smart HTML Table Preview
**Before**: All tables hidden → 2 API calls for `df.head()`
```python
run_simple_code("df.head()")      # → "Use inspect_variable()"
inspect_variable("df")            # → Finally see 5 rows
```

**After**: Small tables (≤10 rows × 10 cols) show inline:
```python
run_simple_code("df.head()")      # → Shows markdown table immediately
# [Data Preview]:
# | Name | Age | City |
# | --- | --- | --- |
# | Alice | 30 | NYC |
```

**Impact**: 50% reduction in API calls, 60% reduction in token usage (500 → 200 tokens)

### Auto-reload
Code changes in `.py` files detected automatically:
```python
# Edit utils.py while kernel runs
# Next cell automatically uses new code - no restart needed!
```

---

## 🧪 Testing

### Run Tests
```bash
# Core tests only (fast, ~45s)
pytest tests/ -m "not optional" -n 4

# All tests including heavy integration
pytest tests/ -n 4

# With coverage
pytest tests/ --cov=src --cov-report=html
```

### Test Categories
- **Core Tests**: 115 tests, no external dependencies (matplotlib/pandas)
- **Optional Tests**: 5 tests, require matplotlib/pandas (marked with `@pytest.mark.optional`)
- **Phase 3 Tests**: 10 tests covering streaming, resource monitoring, visualization, and production edge cases
- **Asset Offload Tests**: 7 tests covering text offloading, garbage collection, and selective retrieval (in `test_asset_offload.py`) ⭐ **NEW**
- **Parallel Execution**: Uses pytest-xdist for 4x speedup

### Test Results
```
127 passed, 2 skipped in 52.92s (parallel mode with -n 15)
```

---

## 🏗️ Architecture

### Component Overview
```
mcp-server-jupyter/
├── src/
│   ├── main.py           # MCP server entry point + tool registration
│   ├── session.py        # SessionManager (kernel lifecycle, async execution)
│   ├── notebook.py       # Notebook CRUD operations
│   ├── notebook_ops.py   # Cell manipulation (move, merge, split)
│   ├── utils.py          # Output sanitization, asset extraction
│   └── environment.py    # Environment detection (conda/venv/system)
├── tests/
│   ├── test_*.py         # 115 tests covering all features
│   └── conftest.py       # Pytest fixtures and configuration
└── assets/               # Auto-created for plots/PDFs
```

### Key Design Patterns

#### 1. Stateful Session Management
Each notebook gets its own kernel session with:
- Dedicated kernel manager
- Async execution queue
- IOPub message listener
- Environment metadata

#### 2. Asynchronous Execution Queue
```python
# Non-blocking execution
exec_id = execute_cell_async(path, index, code)  # Returns immediately
status = get_execution_status(path, exec_id)     # Check later
# Status: queued → running → completed/error/timeout
```

#### 3. Output Sanitization Pipeline
```python
Raw Output → Asset Extraction → HTML Table Conversion → ANSI Stripping → Truncation → Clean Text
```

---

## 📖 Configuration

### pytest Configuration (pyproject.toml)
```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
asyncio_mode = "auto"
markers = [
    "optional: marks tests as optional (heavy integration tests)"
]
```

### Black Formatter
```toml
[tool.black]
line-length = 100
target-version = ["py310", "py311", "py312"]
```

### Run Black
```bash
black src/ tests/
black --check src/ tests/  # Check only, no changes
```

---

## 📋 Recent Updates

### January 2026
- ✅ **Asset-Based Output Storage** ⭐ **NEW**
  - Large text outputs (>2KB or >50 lines) automatically offloaded to `assets/text_*.txt`
  - Preview stubs sent to VS Code/Agent with truncation markers
  - `read_asset()` tool for selective retrieval (grep, pagination, line ranges)
  - Auto-cleanup on kernel stop via reference-counting garbage collection
  - 98% context reduction for large outputs (50MB → 2KB stub)
  - Test coverage: 7 new tests in `tests/test_asset_offload.py`
- ✅ **Handoff Protocol for VS Code Extensions**
  - `detect_sync_needed()` - Detects when kernel state diverges from disk
  - `sync_state_from_disk()` - Rebuilds kernel state after human edits
  - Solves "Split Brain" problem for agent ↔ human workflows
  - See [Handoff Protocol](#-handoff-protocol) above for architecture details
- ✅ **Phase 3: Agent Observability Features + Production Hardening**
  - Streaming feedback for long-running cells (poll for incremental outputs)
  - Resource monitoring (CPU/RAM usage for auto-restart logic)
  - Static visualization rendering (Plotly/Bokeh output PNG/SVG instead of JS)
  - **clear_output** message handling (prevents file size explosion from progress bars/tqdm)
  - Graceful degradation for missing visualization libraries (kaleido/matplotlib/bokeh)
- ✅ **Test suite expansion**: Now 127 passing tests (up from 120)
- ✅ **Fixed race condition in async execution**: `get_execution_status()` now correctly tracks queued executions before queue processing begins
- ✅ **Parallel test stability**: All tests pass consistently with 15 workers (pytest -n 15)
- ✅ **Removed flaky test markers**: Test suite fully stable

### Previous Updates
- Security fixes for variable inspection (removed `eval()` usage)
- Smart HTML table preview (50% reduction in API calls)
- Asset extraction for plots/PDFs (98% context reduction)
- Execution provenance tracking with environment metadata
- Auto-reload support for code changes

---

## 🤝 Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for:
- Architecture deep-dive
- Branching strategy
- Code style guidelines
- How to add new tools
- Test requirements

### Quick Contribution Guide
1. Create feature branch: `git checkout -b feature/my-feature`
2. Make changes with Black formatting: `black src/ tests/`
3. Add tests: `pytest tests/ -k test_my_feature`
4. Ensure all tests pass: `pytest tests/ -m "not optional" -n 4`
5. Submit PR with clear description

---

## 📄 Documentation

All documentation is consolidated into two files:
- **[README.md](./README.md)** (this file): Installation, features, usage, security, testing
- **[CONTRIBUTING.md](./CONTRIBUTING.md)**: Development guide, architecture, design patterns, contribution workflow

---

## 🐛 Known Issues & Limitations

### Test Warnings (Harmless)
```
RuntimeWarning: Proactor event loop does not implement add_reader family of methods required for zmq
```
**Cause**: Windows event loop policy incompatibility with ZMQ  
**Impact**: None - tests pass correctly  
**Solution**: Already handled in code, warning can be ignored

### Optional Tests
Some tests require matplotlib/pandas and are marked as `optional`:
- `test_end_to_end_asset_extraction_and_provenance`
- `test_inspect_variable_integration`
- `test_multiple_asset_types`

**Run optional tests**: `pytest -m optional`

---

## 📊 Performance Benchmarks

| Operation | Time | Notes |
|-----------|------|-------|
| Kernel startup | ~1-2s | Includes environment detection + autoreload |
| Cell execution (simple) | ~50-200ms | `print("hello")` |
| Cell execution (heavy) | Variable | Depends on code complexity |
| Asset extraction | ~10-50ms | Per image/PDF |
| Full test suite | ~45s | 109 tests, parallel mode (pytest -n 4) |
| Full test suite | ~86s | 110 tests, sequential mode |

---

## 🙏 Credits

Built with:
- [MCP SDK](https://github.com/anthropics/mcp) - Model Context Protocol
- [Jupyter Client](https://github.com/jupyter/jupyter_client) - Kernel management
- [nbformat](https://github.com/jupyter/nbformat) - Notebook file format
- [ipykernel](https://github.com/ipython/ipykernel) - IPython kernel for Jupyter

---

## 📝 License

[Your License Here]

---

## 🔗 Quick Links

- **Installation**: [See above](#-installation)
- **Quick Start**: [See above](#-quick-start-guide)
- **Tool Categories**: [See above](#-tool-categories)
- **Contributing**: [CONTRIBUTING.md](./CONTRIBUTING.md)
- **Architecture**: [CONTRIBUTING.md - Architecture Section](./CONTRIBUTING.md#architecture)
- **Security Features**: [See above](#-security-features)

---

## 📞 Support

For issues, questions, or contributions:
1. Check this README and [CONTRIBUTING.md](./CONTRIBUTING.md)
2. Review tool categories and examples above
3. Open an issue with detailed description and reproduction steps
