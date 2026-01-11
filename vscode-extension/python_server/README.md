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
> **Use Case**: When building a VS Code extension or UI on top of this server, these tools solve the "Split Brain" problem where the agent's kernel state diverges from disk after human intervention. See [HANDOFF_PROTOCOL.md](./HANDOFF_PROTOCOL.md) for full details.

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
- **Parallel Execution**: Uses pytest-xdist for 4x speedup

### Test Results
```
120 passed, 2 skipped in 52.92s (parallel mode with -n 15)
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
- ✅ **Handoff Protocol for VS Code Extensions** ⭐ NEW
  - `detect_sync_needed()` - Detects when kernel state diverges from disk
  - `sync_state_from_disk()` - Rebuilds kernel state after human edits
  - Solves "Split Brain" problem for agent ↔ human workflows
  - See [HANDOFF_PROTOCOL.md](./HANDOFF_PROTOCOL.md) for architecture details
- ✅ **Phase 3: Agent Observability Features + Production Hardening**
  - Streaming feedback for long-running cells (poll for incremental outputs)
  - Resource monitoring (CPU/RAM usage for auto-restart logic)
  - Static visualization rendering (Plotly/Bokeh output PNG/SVG instead of JS)
  - **clear_output** message handling (prevents file size explosion from progress bars/tqdm)
  - Graceful degradation for missing visualization libraries (kaleido/matplotlib/bokeh)
- ✅ **Test suite expansion**: Now 120 passing tests (up from 110)
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
