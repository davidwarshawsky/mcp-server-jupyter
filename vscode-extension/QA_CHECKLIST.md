# Release QA Checklist

This checklist ensures the VS Code extension works in real-world scenarios before release. These are **manual tests** that verify the entire user experience, not just unit tests.

---

## Pre-Release Verification

### 1. Clean Install Test (Fresh Environment)

**Purpose**: Verify first-time user experience

- [ ] Uninstall extension: `code --uninstall-extension warshawsky-research.mcp-agent-kernel`
- [ ] Delete extension data: `rm -rf ~/.vscode/extensions/warshawsky*`
- [ ] Delete VS Code workspace storage: `rm -rf ~/Library/Application\ Support/Code/User/workspaceStorage/*` (macOS)
- [ ] Install VSIX: `code --install-extension mcp-agent-kernel-*.vsix`
- [ ] Restart VS Code
- [ ] **PASS CRITERIA**: 
  - Setup Wizard opens automatically on first launch
  - Welcome screen shows "Getting Started" steps
  - No error notifications appear

### 2. The "No Python" Path (Graceful Degradation)

**Purpose**: Verify error handling when Python is not available

- [ ] Rename or temporarily remove Python from PATH: `mv /usr/bin/python3 /usr/bin/python3.bak`
- [ ] Open VS Code and create a new notebook
- [ ] Try to execute a cell
- [ ] **PASS CRITERIA**:
  - Extension shows clear error message: "Python not found"
  - Error includes actionable link: "Download Python"
  - Extension doesn't crash or hang
  - After restoring Python, extension recovers without restart

### 3. Windows Compatibility Test

**Purpose**: Verify subprocess spawning works on Windows (common failure point)

**Platform**: Windows 10/11

- [ ] Install extension from VSIX on Windows
- [ ] Open a notebook with a simple cell: `print('Windows test')`
- [ ] Execute the cell
- [ ] **PASS CRITERIA**:
  - Cell executes successfully (no "spawn ENOENT" error)
  - Output appears correctly
  - No PATH quoting issues in error logs
  - Check Output panel → "MCP Server" for clean startup logs

### 4. The Superpower Check (Feature Verification)

**Purpose**: Verify all Superpower features work end-to-end

#### 4a. DuckDB SQL Queries

- [ ] Create a notebook with:
  ```python
  import pandas as pd
  df_sales = pd.DataFrame({'region': ['East', 'West', 'North'], 'revenue': [100, 200, 150]})
  ```
- [ ] In Claude Desktop (connected to extension):
  - Type: "Query my DataFrame with SQL: SELECT region, revenue FROM df_sales WHERE revenue > 100"
- [ ] **PASS CRITERIA**:
  - Agent uses `query_dataframes` tool
  - Returns correct results in markdown table
  - No DuckDB installation errors

#### 4b. Auto-EDA (Auto-Analyst Prompt)

- [ ] Create a notebook, load a CSV dataset (e.g., `df = pd.read_csv('data.csv')`)
- [ ] In Claude Desktop:
  - Type: `/prompt auto-analyst`
  - Type: "Analyze this dataset"
- [ ] **PASS CRITERIA**:
  - Agent autonomously generates 3+ plots
  - Plots saved to `assets/` directory
  - Summary Markdown cell created with insights
  - Execution completes in < 2 minutes

#### 4c. Time Travel Debugging

- [ ] Execute a cell that saves state: `x = 42`
- [ ] In Claude Desktop: "Save a checkpoint called 'before_crash'"
- [ ] Execute bad code: `undefined_variable + 123`
- [ ] In Claude Desktop: "Restore the checkpoint 'before_crash'"
- [ ] Verify `x` still equals 42
- [ ] **PASS CRITERIA**:
  - `save_checkpoint` creates checkpoint successfully
  - `load_checkpoint` restores kernel state
  - Variables persist after rollback

### 5. Large Output Handling (Asset Offloading)

**Purpose**: Verify extension doesn't crash on large outputs

- [ ] Create a cell with massive output:
  ```python
  for i in range(10000):
      print(f"Line {i}: " + "x" * 100)
  ```
- [ ] Execute the cell
- [ ] **PASS CRITERIA**:
  - Extension does not freeze or crash
  - Output is truncated with `...` or saved to `assets/text_*.txt`
  - VS Code remains responsive
  - Check output size in Output panel < 5KB

### 6. Multi-Notebook Test (Session Isolation)

**Purpose**: Verify multiple notebooks don't interfere with each other

- [ ] Open Notebook A, execute: `x = 100`
- [ ] Open Notebook B, execute: `x = 200`
- [ ] Return to Notebook A, execute: `print(x)`
- [ ] **PASS CRITERIA**:
  - Notebook A prints `100` (not `200`)
  - Kernels are isolated by notebook path
  - No session confusion in logs

### 7. WebSocket Reconnection Test

**Purpose**: Verify extension handles network interruptions

- [ ] Start executing a long-running cell (e.g., `time.sleep(30)`)
- [ ] During execution, kill the Python server process manually
- [ ] Wait for server to restart (via Reaper)
- [ ] Try executing another cell
- [ ] **PASS CRITERIA**:
  - Extension detects disconnection
  - Shows notification: "Reconnecting to server..."
  - Successfully reconnects within 10 seconds
  - Subsequent cells execute normally

### 8. Error Recovery Test

**Purpose**: Verify kernel doesn't hang after errors

- [ ] Execute cell with syntax error: `print('missing quote)`
- [ ] Execute cell with runtime error: `1 / 0`
- [ ] Execute cell with import error: `import nonexistent_module`
- [ ] Execute valid cell: `print('Still alive')`
- [ ] **PASS CRITERIA**:
  - All errors displayed clearly with tracebacks
  - Kernel remains responsive after each error
  - Final valid cell executes successfully

### 9. Consumer Prompts Test (Claude Desktop Integration)

**Purpose**: Verify `/prompt` command works in Claude Desktop

- [ ] Connect Claude Desktop to MCP server (via extension)
- [ ] Type: `/prompt jupyter-expert`
- [ ] Verify persona activates (agent mentions "Search → Inspect → Sync")
- [ ] Type: `/prompt autonomous-researcher`
- [ ] Verify OODA loop persona activates
- [ ] **PASS CRITERIA**:
  - All 3 prompts load without errors
  - Agent behavior changes with each prompt
  - Prompts reference correct tool names

### 10. Package Size Test (Distribution)

**Purpose**: Verify VSIX is not bloated but has all dependencies

- [ ] Run: `./scripts/verify_package.sh`
- [ ] Check VSIX size (should be 5-15 MB)
- [ ] **PASS CRITERIA**:
  - Script reports: "SUCCESS: VSIX Package Verified"
  - Wheel count >= 5
  - All critical packages present (mcp, pydantic, jupyter_client, etc.)

---

## Cross-Platform Testing Matrix

Test the extension on all supported platforms:

| Platform | Clean Install | Execute Cell | Superpowers | Asset Offload | Status |
|----------|---------------|--------------|-------------|---------------|--------|
| macOS (Intel) | ☐ | ☐ | ☐ | ☐ | ⏳ |
| macOS (Apple Silicon) | ☐ | ☐ | ☐ | ☐ | ⏳ |
| Windows 10 | ☐ | ☐ | ☐ | ☐ | ⏳ |
| Windows 11 | ☐ | ☐ | ☐ | ☐ | ⏳ |
| Ubuntu 22.04 | ☐ | ☐ | ☐ | ☐ | ⏳ |
| Ubuntu 24.04 | ☐ | ☐ | ☐ | ☐ | ⏳ |

---

## Known Issues & Workarounds

### Issue: "Python not found" on Windows even though Python is installed

**Workaround**: Add Python to PATH manually or set `mcp-jupyter.pythonPath` in settings.

### Issue: Server takes >30 seconds to start on first launch

**Expected Behavior**: First launch installs dependencies. Subsequent launches should be < 5 seconds.

### Issue: Plots not rendering in VS Code

**Workaround**: Plots are saved to `assets/` directory. Open them manually or use image preview extension.

---

## Release Sign-Off

Before publishing to VS Code Marketplace, ensure:

- [ ] All checklist items pass on at least 2 platforms
- [ ] `verify_package.sh` reports success
- [ ] Integration tests pass: `npm test`
- [ ] README includes installation instructions
- [ ] CHANGELOG updated with new features
- [ ] Version bumped in package.json
- [ ] Git tag created: `git tag v1.0.0`

**Signed off by**: ________________  
**Date**: ________________  
**Version**: ________________

---

## Emergency Rollback Plan

If a critical bug is discovered post-release:

1. Unpublish extension: `vsce unpublish warshawsky-research.mcp-agent-kernel`
2. Fix the bug in a hotfix branch
3. Increment patch version (e.g., 1.0.0 → 1.0.1)
4. Re-run this entire checklist
5. Republish

---

## Notes

- **Automation Gap**: Setup Wizard (WebView) testing is manual because VS Code doesn't expose WebView testing APIs easily.
- **Integration Tests**: Automated tests in `server_integration.test.ts` cover 70% of these scenarios.
- **Manual Testing Time**: Expect 60-90 minutes for full checklist on one platform.

---

**Last Updated**: 2026-01-15  
**Checklist Version**: 1.0
