# Architecture Remediation Plan

This document addresses the critical flaws identified in the `mcp-server-jupyter` architecture.

## 1. Data Persistence & Handoff (The "Split Brain" Problem)
**Critique:** "Re-executing cells to sync state is catastrophic for Data Gravity (30GB dataframes)."
**Remediation:**
- **Short Term:** Implement `dill`-based session checkpointing.
    - Add `save_checkpoint(path)` and `load_checkpoint(path)` tools.
    - When `sync_state_from_disk` is called, prefer loading a checkpoint over re-execution if the graph hasn't diverged.
- **Long Term:** Adopt "Variable Mirroring". The Agent should not own the kernel; it should attach to a persistent kernel managed by VS Code or a Jupyter Server.

## 2. File System Race Conditions
**Critique:** "MCP Server writes to disk, fighting VS Code's buffer."
**Remediation:**
- **Immediate Fix:** Implement `apply_edit` tool that returns a JSON description of the edit (insert/replace).
- **Architecture Change:** The VS Code Client (`mcp-agent-kernel` extension) must handle the actual file writes. The MCP Server should function as a *Calculator/Reasoner*, returning *intent* ("Insert code at index 3") rather than performing side effects on the filesystem.

## 3. Communication Architecture
**Critique:** "Stdio polling every 500ms is sluggish and brittle."
**Remediation:**
- **Medium Term:** Switch to WebSockets for the MCP transport layer if supported, or use ZMQ for the internal Kernel <-> MCP communication (Standard Jupyter Protocol).
- **Optimization:** Increase polling frequency for active execution streams, but implementation of `notifications/message` from MCP to push updates to VS Code is required to eliminate polling.

## 4. Security
**Critique:** "`inspect_variable` executes unsafe code (str/repr) in the kernel."
**Remediation:**
- **Immediate Fix:** Sanitize `variable_name` input to prevent injection. Wrap object inspection in strict time-boxed execution. Avoid calling `str()` on unknown objects where possible, or do so in a separate thread.
- **Long Term:** Use the Jupyter Debugger Protocol (DAP) to inspect variables without executing kernel code.

## 5. Visualization
**Critique:** "Static backends break human interactivity."
**Remediation:**
- **Fix:** Update `sanitize_outputs` to pass through MIME bundles (`application/vnd.plotly.v1+json`) instead of flattening to text. The VS Code extension must then render these MIME types in the chat interface or a webview, rather than just treating the output as text.

---

## Implemented Fixes (In Progress)

### 1. Security Hardening: `inspect_variable`
I am patching `src/main.py` to:
- Validate that `variable_name` is a valid Python identifier.
- Wrap inspection logic to handle `__repr__` bombs gracefully.

### 2. State Preservation: `dill` Support
I am adding optional `dill` serialization to `src/session.py` to allow snapshotting heavy states.
