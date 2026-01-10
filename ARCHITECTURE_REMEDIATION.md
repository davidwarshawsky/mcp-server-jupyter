# Architecture Remediation Plan (Updated Jan 2026)

This document tracks the remediation of critical architectural flaws identified in the "Forensic Teardown".

## 🛑 Critical Issues & Status

| Issue | Severity | Status | Fix Implemented |
|-------|----------|--------|-----------------|
| **"Split Brain" Metadata** | Critical | **Fixed** | Removed `.mcp` sidecar. Metadata now stored in `.ipynb` `cell.metadata.mcp`. |
| **Handoff Race Condition** | Critical | **Fixed** | Replaced mtime timestamps with Content Hashing (SHA-256). |
| **Fragile Shell Checkouts** | High | **In Progress** | Refactoring `git_tools.py` to use `GitPython` instead of `subprocess`. |
| **Polling Loop (Latency)** | High | Pending | Needs MCP Notifications implementation. |
| **Environment Fragility** | High | Pending | Needs direct binary execution (no conda activate). |
| **Security (Eval)** | High | Pending | Needs Inspector Sandbox. |

## 🛠️ Implemented Fixes (Week 1: Stabilization)

### 1. Unified Metadata (Killing the Sidecar)
- **Problem:** Storing state in `.mcp/provenance.json` caused data loss on file rename/move.
- **Fix:** 
    - Deleted `src/provenance.py`.
    - Updated `src/session.py` to calculate execution metadata and pass it to `src/notebook.py`.
    - Metadata is now stored atomically in `cell.metadata.mcp` within the notebook JSON.

### 2. Content-Addressable State (Fixing Handoff)
- **Problem:** `detect_sync_needed` relied on file timestamps (`mtime`), causing false positives/negatives with Git branch switching.
- **Fix:**
    - Implemented `utils.get_cell_hash(source)` (SHA-256).
    - Rewrote `detect_sync_needed` in `src/main.py` to compare `current_hash` vs `last_executed_hash`.
    - System is now immune to filesystem timestamp quirks.

### 3. Git Tooling Reliability
- **Problem:** `git_tools.py` relied on fragile `subprocess.run(['git', ...])` calls.
- **Fix:**
    - Added `GitPython` dependency.
    - Refactored `create_agent_branch` and `commit_agent_work` to use native Git bindings.

## 📅 Remaining Roadmap

### Week 2: Reliability
- [ ] **Environment Hardening:** Stop using `conda activate` or shell execution. direct execution of python binaries.
- [ ] **Defensive Checkpointing:** Wrap `dill` in try/except blocks to strictly serialize only safe types (pandas/numpy/lists) and ignore sockets/locks.

### Week 3: Performance
- [ ] **Event-Driven Architecture:** Replace VS Code client polling with MCP Server-Sent Notifications (`notebook/output`).

### Week 4: Cleanup
- [ ] Standardize logging and error reporting.
- [ ] Finalize `README.md` to reflect "Beta" status.

