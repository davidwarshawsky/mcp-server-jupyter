# MCP Server Jupyter: Production-Grade AI Agent + Human Collaboration for Notebooks

A **Model Context Protocol (MCP)** server that enables safe, state-aware AI agents to collaborate with humans in Jupyter notebooks. Solves the "Split Brain" problem where agents and humans can diverge in kernel state, cell indices, and edits.

## The Problem This Solves

Traditional notebook AI assistants suffer from three critical flaws:

1. **"Data Gravity"**: Re-running a 30GB data load to sync state is non-viable for real data science.
2. **"File vs. Buffer Race Condition"**: Agent writes to disk while human edits in VS Code → conflict dialogs.
3. **"Index Blindness"**: Agent reads stale disk state, executes the wrong cell because the buffer has new cells the agent doesn't see.

This project implements a **Buffer-Based, State-Aware Architecture** that:
- Uses **Dill checkpoints** to snapshot kernel state (no re-execution).
- Sends cell code from VS Code buffer (eliminates disk reads).
- Injects notebook structure into tool calls (prevents index drift).
- Proposes edits via JSON (clean WorkspaceEdit, no conflicts).

## Architecture: The Four Pillars

### Phase 1: Robust Environment & State Management
**Problem**: 
- **"Split Brain"**: Agent edits vs Human edits leads to divergence.
- **"Conda Nightmare"**: Manually hacking `PATH` fails to activate complex ML libraries (CUDA/MKL).
- **"Data Gravity"**: Re-running a 30GB data load to sync state is non-viable.

**Solution**: 
- **Incremental State Sync**: Using `sync_state_from_disk(strategy="incremental")`, the server identifies the first "dirty" or missing cell and re-runs only from that point forward.
- **Native Conda Activation**: Uses `conda run` to ensure deep environment activation (LD_LIBRARY_PATH, etc).
- **Dill Checkpoints**: Snapshots kernel state to disk for instant recovery (Planned).

```python
# Server receives code directly from buffer
@mcp.tool()
async def run_cell_async(notebook_path: str, index: int, code_override: Optional[str] = None):
    # Use buffer if provided, fallback to disk only if disconnected
    code = code_override if code_override is not None else read_from_disk(notebook_path, index)
    return await execute(code)
```

### Phase 2: Rich Visualization (MIME Types)
**Problem**: Interactive plots (Plotly) were flattened to static images.  
**Solution**: Return raw MIME bundles (`application/vnd.plotly.v1+json`) so VS Code renders them interactively.

```python
# sanitize_outputs now returns:
{
    "llm_summary": "Text for agent context",
    "raw_outputs": [
        {
            "output_type": "display_data",
            "data": {
                "application/vnd.plotly.v1+json": {...}  # PLOTLY IS NOW INTERACTIVE
            }
        }
    ]
}
```

### Phase 3: Dill-Based Checkpointing
**Problem**: "Data Gravity" — 10-minute data loads cannot be re-run.  
**Solution**: Snapshot the kernel heap to `.pkl` files. Restore with one command.

```python
@mcp.tool()
async def save_checkpoint(notebook_path: str, name: str = "checkpoint"):
    # Saves kernel variables to .mcp/checkpoint.pkl
    # Includes granular error diagnosis for unpicklable objects (e.g., database connections)
    
@mcp.tool()
async def load_checkpoint(notebook_path: str, name: str = "checkpoint"):
    # Restores all variables in seconds (not minutes re-running cells)
```

### Phase 4: The Handoff Protocol (Split-Brain Prevention)
**Problem**: Human edits notebook; agent doesn't know; agent's cell indices are wrong.  
**Solution**:
1. When notebook opens, client calls `detect_sync_needed()`.
2. Server checks if disk ≠ kernel state.
3. If diverged, UI shows "Sync Required" button (not automatic to avoid surprises).
4. Agent can call `sync_state_from_disk()` to rebuild state.

```python
@mcp.tool()
def detect_sync_needed(notebook_path: str):
    # Returns:
    # {
    #   "sync_needed": true,
    #   "reason": "Found 3 cells without agent metadata",
    #   "recommendation": "sync_state_from_disk"
    # }
```

### Phase 5: Buffer-Aware Navigation
**Problem**: Agent calls `get_notebook_outline()` which reads stale disk state.  
**Solution**: VS Code Client injects the live buffer structure into the tool call.

```typescript
// In mcpClient.ts: Argument Injection
if (toolName === 'get_notebook_outline' && !args.structure_override) {
    // Read VS Code buffer (NOT disk)
    args.structure_override = vscode.notebookDocuments.getCells()
        .map(cell => ({ index, type, source, id }));
}
```

Now the agent always sees the truth: the current buffer state.

### Phase 6: Security & Resilience (New)
**Problem**: Code executed by agents ran with full user privileges, and infinite loops could hang the server. Complex environments (Conda) often failed to activate properly.
**Solution**: 
- **Docker Sandboxing**: `start_kernel` accepts a `docker_image` parameter to run code in an isolated container.
- **Robust Timeouts**: Enforcement of execution limits prevents zombie processes.
- **Environment Activation**: Advanced shell simulation ensures `conda activate` and `source venv/bin/activate` work correctly, preserving sensitive PATH configurations for ML libraries.

## Installation

### Server Side (Python)

```bash
cd tools/mcp-server-jupyter
pip install -e .
# Optional: For checkpoint support
pip install dill
```

### Client Side (VS Code Extension)

```bash
cd vscode-extension
npm install
npm run compile
```

Then in VS Code: `Extensions` → `Install from VSIX` → select the built package.

## Quick Start

### 1. Open a Notebook in VS Code

```bash
code my_notebook.ipynb
```

### 2. Start a Kernel

The extension will automatically start an MCP kernel when you first execute a cell.

Alternatively, use the "MCP Agent Kernel" option from VS Code's kernel selector.

### 3. Run Cells (Buffer-Safe)

Click "Run Cell" in VS Code. The cell code from your *buffer* (not disk) is sent to the kernel.

### 4. Save Checkpoint (Optional)

If you have expensive data loading:

```python
# In a cell
# The agent can call:
# agent.save_checkpoint("my_data_loaded")
# Later, after human editing:
# agent.load_checkpoint("my_data_loaded")  # Restores in seconds
```

### 5. Propose Edits (Not Direct Writes)

When the agent wants to modify a cell:

```python
# Agent calls (not edit_cell):
propose_edit(notebook_path, index=2, new_content="...")
```

VS Code automatically applies the edit via `WorkspaceEdit` (safe, with undo history).

## API Reference

### Execution Tools

| Tool | Purpose |
|------|---------|
| `start_kernel(notebook_path, venv_path)` | Boot kernel for a notebook |
| `stop_kernel(notebook_path)` | Shut down kernel |
| `run_cell_async(notebook_path, index, code_override)` | Execute cell (buffer-safe) |
| `get_execution_stream(notebook_path, task_id)` | Stream outputs in real-time |
| `interrupt_kernel(notebook_path)` | Stop running cell |

### State Management

| Tool | Purpose |
|------|---------|
| `save_checkpoint(notebook_path, name)` | Snapshot kernel heap (Dill) |
| `load_checkpoint(notebook_path, name)` | Restore from checkpoint |
| `get_kernel_info(notebook_path)` | List active variables |
| `detect_sync_needed(notebook_path)` | Check for split-brain |
| `sync_state_from_disk(notebook_path)` | Re-execute to rebuild state |

### Navigation & Modification

| Tool | Purpose |
|------|---------|
| `get_notebook_outline(notebook_path, structure_override)` | Cell list (buffer-injected) |
| `propose_edit(notebook_path, index, new_content)` | Suggest edit (no disk write) |
| `read_cell_smart(notebook_path, index)` | Read cell source/output |
| `search_notebook(notebook_path, query)` | Find cells by pattern |
| `inspect_variable(notebook_path, var_name)` | Safe variable inspection |

### Safety

| Tool | Purpose |
|------|---------|
| `append_cell(notebook_path, content, type)` | Add cell (safe) |
| `insert_cell(notebook_path, index, content)` | Insert cell at position |
| `delete_cell(notebook_path, index)` | Remove cell |

## How It Works: The Message Flow

```
VS Code User Types in Cell 5
        ↓
VS Code Buffer: [Cell 0, Cell 1, Cell 2, Cell 3, Cell 4, Cell 5 (unsaved)]
        ↓
User clicks "Run Cell 5"
        ↓
notebookController.ts calls: runCellAsync(path, 5, cell5.document.getText())
        ↓
mcpClient.ts BEFORE sending:
  - Intercepts get_notebook_outline → injects all 6 cells
  - Intercepts run_cell_async → sends actual buffer code
        ↓
main.py receives:
  - code_override: "print('This is the actual code')"
  - structure_override: [6 cells with correct indices]
        ↓
session.py executes in kernel without disk reads
        ↓
Output streamed back to VS Code
        ↓
Plotly charts render interactively (raw MIME type)
```

## Configuration

### Python Environment Selection

Click the environment icon in VS Code status bar to select:
- System Python
- Virtual environment (`.venv`)
- Conda environment

### Polling Interval

In VS Code settings:

```json
"mcp-jupyter.pollingInterval": 500  // milliseconds
```

### Notebook Metadata

Saved environment is stored in notebook metadata:

```json
{
  "metadata": {
    "mcp-jupyter": {
      "environment": {
        "type": "venv",
        "path": "/home/user/.venv",
        "name": "My Project"
      }
    }
  }
}
```

## Troubleshooting

### "Notebook State Sync Required"

**Cause**: You edited the notebook externally (git merge, manual edit) or switched kernels.

**Solution**: Click "Sync State Now" to re-execute cells and rebuild kernel state.

### Checkpoint Save Fails

**Cause**: A variable cannot be pickled (e.g., database connection, GPU tensor, file handle).

**Error Message**:
```
Checkpoint Failed. Analyzing unpicklable variables...
FAILED: The following variables cannot be saved: db_conn (MySQLConnection)
Suggestion: Delete these variables (del var_name) or recreate them after reload.
```

**Solution**:
```python
del db_conn  # Remove the unpicklable object
save_checkpoint("my_data")  # Try again
```

### Agent Edits Don't Show Up

**Cause**: `propose_edit` was called but the client didn't intercept it.

**Check**: Open VS Code Output panel → "MCP Jupyter Server" → look for edit proposals.

**Solution**: Ensure extension is up-to-date and kernel is running.

## Architecture Decisions

### Why Dill Over Pickle?

Dill handles more complex objects (lambdas, nested functions, closures). Pickle fails on these.

### Why Buffer Injection Over Server-Side Caching?

Server-side session caching requires persistent state tracking and websocket upgrades. Client-side injection is simpler and always has the ground truth (the buffer).

### Why JSON Proposals Over Direct Edits?

Direct disk writes conflict with VS Code's buffer. Proposals via `_mcp_action` signal let the client decide when to apply (preserves undo history, shows diffs).

## Security Considerations

### Code Execution

This system executes arbitrary code in a kernel (that's the point). **Recommendations**:

- Run in a **sandboxed environment** (Docker, nsjail, or VM).
- Use **restricted virtual environments** for untrusted code.
- Never use the system Python.

### Variable Inspection

`inspect_variable` avoids calling `str()` or `repr()` on untrusted objects (can trigger malicious `__str__` methods). It uses safe type checks for primitives and delegates to pandas/numpy for known types.

### Checkpoints

Dill checkpoints are pickled Python objects. Only load checkpoints from **trusted sources**. A malicious `.pkl` file can execute code during deserialization.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and pull request guidelines.

## Roadmap

- [ ] **WebSocket Transport**: Replace 500ms polling with push-based updates.
- [ ] **Jupyter Server Integration**: Proxy to standard Jupyter Server instead of custom session management.
- [ ] **Remote Kernels**: Support Kubeflow, Databricks, SageMaker.
- [ ] **Variable Mirroring**: Snapshot only changed variables for faster sync.
- [ ] **Notebook Diffs**: Show Agent vs. User edits side-by-side.

## License

MIT

## Acknowledgments

This project solves the architectural problems identified in the "Rube Goldberg" critique of early AI notebook agents. The Buffer-Based, State-Aware design pattern is applicable to any system where an AI agent and human collaborate on shared mutable state.

---

**Status**: Production-Ready (as of January 2026)

For questions or issues, open a GitHub issue or reach out to the maintainers.
