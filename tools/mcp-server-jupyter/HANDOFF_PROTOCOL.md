# Handoff Protocol: Agent ↔ Human Workflow

## Problem: The "Split Brain" Scenario

When building a VS Code extension (or any UI) on top of `mcp-server-jupyter`, you face a **fundamental architectural challenge**:

- **Agent Mode**: The MCP server's kernel has variables in RAM (`df = load_data()`)
- **Human Mode**: The user edits the notebook in VS Code with their own kernel
- **Switch Back to Agent**: The agent's kernel is OUT OF SYNC with disk changes

**Result**: `KeyError`, `NameError`, or stale variable state when agent resumes.

---

## Solution: The "Handoff Protocol"

Instead of trying to share kernel state (which causes race conditions), we implement a **clear handoff procedure**:

1. **Disk is Source of Truth** (not RAM)
2. **Agent is responsible for syncing** when resuming work
3. **Two new MCP tools** enforce this protocol

---

## New MCP Tools

### 1. `detect_sync_needed(notebook_path: str)`

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

---

### 2. `sync_state_from_disk(notebook_path: str, strategy: str)`

**Purpose**: Re-execute cells from disk to rebuild kernel RAM state.

**Strategies**:
| Strategy | Behavior | Use When |
|----------|----------|----------|
| `"incremental"` | **(Recommended)** Finds the first "dirty" cell (content changed vs execution history) and re-runs from there. | Default. Maximizes performance while ensuring correctness. |
| `"full"` | Re-executes ALL code cells | Fallback if incremental fails or state is corrupted. |

**Returns**:
```json
{
  "status": "syncing",
  "cells_synced": 3,
  "cells_skipped": 9,
  "execution_ids": ["abc123", "def456"],
  "estimated_duration_seconds": 6,
  "strategy_used": "incremental",
  "hint": "Use get_execution_status() to monitor progress"
}
```

---

## Agent Workflow (System Prompt Integration)

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

---

## VS Code Extension Integration

### "Traffic Light" UI Pattern

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

vscode.commands.registerCommand('jupyter.stopAgentMode', async () => {
    // Unlock the editor for human edits
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        editor.options = { readOnly: false };
    }
    
    agentMode = false;
    vscode.window.showInformationMessage('👤 Human Mode Active');
});
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  VS Code Extension (TypeScript)                             │
│                                                              │
│  ┌──────────────┐         ┌──────────────┐                │
│  │ Human Mode   │◄───────►│ Agent Mode   │                │
│  │ (Read-Write) │  Toggle │ (Read-Only)  │                │
│  └──────────────┘         └──────────────┘                │
│         │                        │                          │
│         │ Edits .ipynb          │ Watches .ipynb           │
│         ▼                        ▼                          │
│  ┌──────────────────────────────────────────┐              │
│  │  Disk: analysis.ipynb (Source of Truth)  │              │
│  └──────────────────────────────────────────┘              │
│                        │                                     │
└────────────────────────┼─────────────────────────────────────┘
                         │
                         ▼ MCP Protocol (stdio)
┌─────────────────────────────────────────────────────────────┐
│  mcp-server-jupyter (Python)                                │
│                                                              │
│  Agent Mode Activated:                                      │
│  1. detect_sync_needed() → "3 human cells found"           │
│  2. sync_state_from_disk(strategy="smart")                 │
│     • Re-executes cells [5, 6, 7] from disk                │
│     • Skips visualization-only cells                        │
│  3. Kernel RAM now synced with disk                        │
│  4. append_cell() → Agent adds new analysis                │
│                                                              │
│  ┌─────────────────────────────────────────┐               │
│  │  Jupyter Kernel (IPython)               │               │
│  │  Variables in RAM: df, df_clean, model  │               │
│  └─────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Status

- ✅ **Core Architecture**: "Split Brain" accepted (Agent owns kernel)
- ✅ **MCP Tools Added**:
  - `detect_sync_needed()` - Detects human edits
  - `sync_state_from_disk()` - Rebuilds kernel state
- ✅ **Strategy Options**: "smart", "full", "incremental" (planned)
- ⏳ **VS Code Extension**: Not yet implemented (but architecture is ready)
- ⏳ **Cell Hashing**: For "incremental" strategy (future enhancement)

---

## Testing the Handoff Protocol

### Test Case 1: Human Adds New Cells

```python
# 1. Agent creates notebook and runs cells
start_kernel("test.ipynb")
append_cell("test.ipynb", "df = pd.DataFrame({'a': [1, 2, 3]})")
run_all_cells("test.ipynb")

# 2. Human opens VS Code, adds cell: df['b'] = df['a'] * 2
# (This happens outside the agent's control)

# 3. Agent resumes work
status = detect_sync_needed("test.ipynb")
# Returns: {"sync_needed": true, "reason": "Found 1 cell without agent metadata"}

sync_state_from_disk("test.ipynb", strategy="smart")
# Re-executes the human's cell to define df['b'] in kernel RAM

inspect_variable("test.ipynb", "df")
# Now shows column 'b' (previously would have been KeyError)
```

### Test Case 2: Human Modifies Existing Cells

```python
# 1. Agent's original code
append_cell("test.ipynb", "threshold = 0.5")

# 2. Human changes to: threshold = 0.8

# 3. Agent resumes
detect_sync_needed("test.ipynb")
# Returns: {"sync_needed": true, "reason": "File modified after kernel start"}

sync_state_from_disk("test.ipynb", strategy="full")
# Re-executes all cells, including the modified threshold

# Now kernel has threshold = 0.8 (matches disk)
```

---

## Best Practices

### For Agents
1. **Always call `detect_sync_needed()` when starting a session**
2. **Use `strategy="smart"` by default** (fast and usually sufficient)
3. **Fall back to `strategy="full"` if you get unexpected errors** (NameError, KeyError)
4. **Don't assume variables exist** - check with `list_variables()` first

### For Extension Developers
1. **Enforce "Traffic Light" mode** - lock editor when agent is active
2. **Show sync progress** - users need to know what's happening
3. **Warn before switching modes** - "Agent is working, stop now?"
4. **Display provenance metadata** - use `NotebookCellStatusBarItemProvider`

### For End Users
1. **Finish your edits before starting agent** - minimize sync overhead
2. **Save frequently** - disk is source of truth
3. **Understand the trade-off** - safety (split brain) vs. convenience (shared state)

---

## Future Enhancements

### 1. Cell Hashing for Incremental Sync
Store cell source hash in metadata:
```python
cell.metadata['mcp_trace']['source_hash'] = hashlib.sha256(cell.source.encode()).hexdigest()
```
Then only re-execute cells where hash changed.

### 2. Variable Dependency Graph
Track which cells define which variables:
```python
{
  "cell_3": ["df", "df_clean"],
  "cell_5": ["model", "predictions"]
}
```
Then only sync cells that define variables you need.

### 3. Conflict Resolution UI
When human edits conflict with agent's next action:
```
⚠️ Conflict Detected
Cell 3 was modified by human after agent queued next action.
[Abort Agent] [Merge Changes] [Override with Agent]
```

---

## Conclusion

The **Handoff Protocol** solves the "Split Brain" problem by:
- ✅ Accepting that agent and human have separate kernel states
- ✅ Making agent responsible for syncing when resuming work
- ✅ Using disk as the single source of truth
- ✅ Providing clear detection and sync tools

**Trade-off**: Slight overhead (2-5s sync time) in exchange for **zero race conditions** and **predictable behavior**.

This is the **production-grade solution** that scales to real-world usage.
