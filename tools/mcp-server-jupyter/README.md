# MCP Server Jupyter

**Stateful, Production-Ready Jupyter Notebook Execution via Model Context Protocol**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-passing-success)](./tests/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## 🚀 Get Started in 60 Seconds

### 1. Installation
This package is designed to be installed in your Python environment, just like `ipykernel`. The accompanying VS Code extension will use the version of this server from the currently selected Python environment.

```bash
pip install mcp-server-jupyter
```

### 2. Start the Server
Run this in a dedicated terminal. It will act as the central "Hub" for all notebook operations.

```bash
mcp-jupyter --transport websocket --port 3000
```
Your MCP server is now running. You can connect to it from an MCP client, such as the official VS Code extension.

---

## 🛡️ Our "Do No Harm" Philosophy
For a tool that programmatically executes code on your behalf, trust is paramount. We designed this server with a core philosophy: **Do No Harm**. Your work and your development environment should always be protected.

Here’s how we put that principle into practice:

*   **File Locking**: To prevent "split-brain" scenarios where both a human and an agent could edit a notebook simultaneously, the server uses file locks. This ensures that only one process can modify a notebook at a time, preventing data corruption and race conditions.
*   **Safe Variable Inspection**: The `inspect_variable` tool uses safe, dictionary-based lookups to retrieve variable information. It explicitly avoids using `eval()`, which can be a vector for code injection attacks.
*   **No Destructive Commands**: The tool's command set is focused on notebook operations. It does not provide general-purpose shell access or commands that could delete files or otherwise harm your workspace.
*   **Clear Provenance**: Every cell executed by the agent includes metadata about the execution, so you always have a clear audit trail of what the agent did.

---

## 🎯 What is This?

An MCP (Model Context Protocol) server that transforms Jupyter notebooks into a **reliable backend API** for AI agents. Execute cells, manipulate notebooks, manage kernels, and inspect variables—all through stateful, production-grade MCP tools.

**Perfect for**: AI agents performing data analysis, scientific computing, visualization, or any Jupyter-based workflow.

---

## ✨ Key Features

### 🌟 Superpower Features
- **🧠 Smart Sync (DAG-Based Execution)**: Intelligent cell re-execution using AST-based dependency analysis. When you edit a cell, the system automatically determines which downstream cells need to be rerun, saving significant execution time.
- **SQL on DataFrames**: Run DuckDB SQL queries directly on pandas/polars DataFrames in memory.
- **Automated EDA**: Generate comprehensive Exploratory Data Analysis reports from a simple prompt.

### 🔒 Production-Ready
- **Security**: SQL injection protection, package installation allowlists, and safe variable inspection.
- **Robustness**: Execution provenance tracking, graceful handling of `clear_output`, execution timeouts, and file locking.
- **Asset Management**: Automatic extraction of plots and offloading of large text outputs to keep notebooks clean and responsive.

---

## 🔮 Core Usage Examples

### Execute Code
```python
# Synchronous (blocks until complete)
execute_cell("analysis.ipynb", cell_index=0)

# Asynchronous (non-blocking)
exec_id = execute_cell_async("analysis.ipynb", cell_index=0, code="import pandas as pd")
status = get_execution_status("analysis.ipynb", exec_id)
```

### Inspect a DataFrame
```python
# Inspect a large DataFrame without crashing the kernel
inspect_variable("analysis.ipynb", "df")
# Returns a summary with shape, columns, memory usage, and a preview.
```

### Query DataFrames with SQL
```python
# Use natural SQL syntax on in-memory DataFrames
query_dataframes("analysis.ipynb", '''
    SELECT region, COUNT(*) as num_orders
    FROM df_sales
    GROUP BY region
''')
```
---

## 🧠 Smart Sync: DAG-Based Execution

Traditional notebooks rerun all cells below an edit. Our Smart Sync feature analyzes your code to build a dependency graph, enabling surgical re-execution that saves time and resources.

### Three Sync Strategies
1.  **Smart Mode (Default)**: Reruns only the cells affected by a change.
2.  **Incremental Mode**: Reruns the changed cell and all subsequent cells.
3.  **Full Mode**: Reruns the entire notebook from scratch.

---

## 📚 Tool Categories

This server provides a comprehensive set of tools for:
- Data Analysis
- Agent-Ready Operations
- Core Kernel and Execution Management
- Handoff Protocol for Agent-Human collaboration
- Notebook and Cell Manipulation (CRUD)
- Metadata and Variable Inspection
- Asset Management

---

## 🤝 Handoff Protocol

The Handoff Protocol solves the "Split Brain" problem where an agent's kernel state can diverge from the notebook file after human edits. It ensures the disk is the source of truth and the agent is responsible for syncing its state before resuming work.

### Key Tools
- `detect_sync_needed()`: Checks if the kernel's state is out of sync with the notebook file.
- `sync_state_from_disk()`: Rebuilds the kernel's state by re-executing cells from the file.

---

## 🧪 Testing

The project includes a comprehensive test suite to ensure reliability and stability.

### Run Tests
```bash
# Run core tests
pytest tests/ -m "not optional"

# Run all tests, including heavy integration tests
pytest tests/
```
The test suite is designed for parallel execution to speed up validation.

---

## 🏗️ Architecture

The server is built around a "Hub and Spoke" model, with a central process managing kernel state and allowing multiple clients (e.g., an AI agent and a VS Code editor) to connect and interact with the same session.

---

## 🤝 Contributing

Contributions are welcome! Please see `CONTRIBUTING.md` for our development guide, architecture deep-dive, and contribution workflow.

---

## 📝 License

Apache-2.0
