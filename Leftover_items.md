# Leftover Items from Day 2 "Zero Friction" Implementation

## Completed ✅

### 1. "Wipeout" Restart Warning
- **File**: `tools/mcp-server-jupyter/src/tools/data_tools.py`
- **Change**: `install_package` now shows explicit warning about memory clearing on kernel restart.

### 2. "Blind Drag-and-Drop" File Upload
- **Backend**: `filesystem_tools.py` has `upload_file` tool (already existed)
- **Frontend**: `mcpClient.ts` - Added `uploadFile()` method
- **Frontend**: `extension.ts` - Added `mcp-jupyter.uploadToKernel` command handler
- **Frontend**: `package.json` - Registered command & Explorer context menu (`explorer/context`)

### 3. "Context Amnesia" Startup Recovery
- **File**: `vscode-extension/src/variableDashboard.ts`
- **Change**: Added `checkContextAmnesia()` method that warns user when kernel is fresh but notebook has execution history.

### 4. "Cost of Curiosity" Cell Tagging
- **File**: `tools/mcp-server-jupyter/src/tools/execution_tools.py`
- **Change**: `run_all_cells` respects `# @frozen`, `# @skip`, `# @expensive` tags
- **File**: `tools/mcp-server-jupyter/src/models.py` - Added `force` argument to `RunAllCellsArgs`

### 5. "Visualization Void" (Partial)
- **File**: `tools/mcp-server-jupyter/src/utils.py`
- **Change**: LLM summary now shows asset paths for generated plots

---

## Still TODO 🔲

### 1. Full "Visualization Void" Implementation
**Problem**: Agent generates plots but cannot "see" or interpret visual outputs.

**Remaining Work**:
- [ ] Hook into Plotly/Matplotlib plot generation to auto-save PNG sidecar
- [ ] Use `kaleido` for static export of Plotly charts
- [ ] Pass image path to agent context for multi-modal understanding
- [ ] Consider base64-encoding small images directly into tool responses

**Files to modify**:
- `tools/mcp-server-jupyter/src/utils.py` - Enhance `sanitize_outputs` to detect charts and trigger static export
- Potentially add a `render_chart_to_png` helper function

### 2. Windows File Permissions for `connection.json`
**Problem**: `os.chmod(conn_file, 0o600)` doesn't provide strict POSIX-like security on Windows.

**Remaining Work**:
- [ ] Use `win32security` ACLs for Windows-specific file permission handling
- [ ] Or document this as an acceptable risk for localhost-only MVP

**Files to modify**:
- `tools/mcp-server-jupyter/src/main.py` - Add Windows-specific permission handling

### 3. Web Extension Compatibility (Browser Shims)
**Problem**: `https-proxy-agent` relies on Node.js modules which crash in browser-based VS Code (vscode.dev, Codespaces).

**Remaining Work**:
- [ ] Wrap proxy logic with `if (typeof process !== 'undefined')` checks
- [ ] Ensure `esbuild`/`webpack` config handles browser shims
- [ ] Test in vscode.dev

**Files to modify**:
- `vscode-extension/src/mcpClient.ts` - Guard proxy imports

### 4. TypeScript Test File Fixes
**Problem**: Test files have type errors (missing `@types/node`, `@types/mocha`).

**Remaining Work**:
- [ ] Ensure `npm install` in vscode-extension includes all dev dependencies
- [ ] Fix test file type annotations

**Files affected**:
- `vscode-extension/test/suite/*.ts`

---

## Previous Session Fixes (Already Merged)

These were implemented in the earlier session and should be present in the codebase:

- ✅ **Token Fatigue**: Zero-config localhost via `~/.mcp-jupyter/connection.json`
- ✅ **State Contamination**: CWD awareness in `check_kernel_resources` and status bar warning
- ✅ **Hidden Dependency Trap**: `install_package` detects `requirements.txt` and prompts to add
- ✅ **Variable Explorer Doppelgänger**: Renamed to "Agent Context (Memory)"
- ✅ **Dead Progress Bar**: `tqdm` output formatting
- ✅ **Pip Install Race**: `requires_restart` flag
- ✅ **Metadata Bloat**: Strip `mcp_trace`/`mcp_execution` on save
