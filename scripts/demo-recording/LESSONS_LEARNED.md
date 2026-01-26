# 🎓 Demo Recording: Lessons Learned & Technical Deep Dive

> **Project:** MCP Jupyter Server - Demo Recording Infrastructure  
> **Created:** 2026-01-22  
> **Author:** Automated via debugging session  
> **Status:** ✅ Fully Working

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [The Journey: From Broken to Working](#the-journey-from-broken-to-working)
3. [Critical Bug Fixes](#critical-bug-fixes)
4. [Docker Environment Setup](#docker-environment-setup)
5. [Playwright Test Architecture](#playwright-test-architecture)
6. [VS Code Extension Insights](#vs-code-extension-insights)
7. [Quick Reference Commands](#quick-reference-commands)
8. [Troubleshooting Guide](#troubleshooting-guide)

---

## Executive Summary

### The Problem

We needed to create demo recordings of the MCP Jupyter extension running in VS Code. This required:
- A reproducible Docker environment running code-server
- Playwright automation to control the VS Code UI
- The MCP extension connecting successfully to its Python server
- Notebook cells rendering and executing

### The Solution

After extensive debugging, we identified and fixed **5 critical issues**:

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| WebSocket auth failing | Token sent in headers, server checks query params | Pass token as `?token=XXX` query param |
| MCP server not responding | Print statements buffered | Add `flush=True` to stderr prints |
| Connection drops | Socket backlog too small (1) | Increase to `listen(100)` |
| Cell selectors not matching | VS Code DOM structure different | Use `.monaco-list-row.code-cell-row` |
| Setup wizard blocking | Config setting ignored | Check `showSetupWizard` in config |

---

## The Journey: From Broken to Working

### Initial State (Broken)

```
❌ Notebook content not rendering
❌ MCP extension shows "Unknown connection error"  
❌ "Failed to reconnect to MCP server after multiple attempts"
❌ Cell execution fails - selectors not matching
```

### Debugging Process

#### Phase 1: Identifying the WebSocket Issue

**Symptom:** WebSocket closed with code 1006 immediately after connection.

**Investigation:**
```bash
# Check MCP server logs in container
docker exec demo-code-server cat "/config/data/logs/*/exthost1/output_logging_*/1-MCP Jupyter Server.log"
```

**Discovery:** The log showed:
```
[stderr] [MCP_PORT]: 33863
MCP Server listening on ws://127.0.0.1:33863/ws
WebSocket closed: 1006 
Connection lost. Attempting automatic reconnection...
❌ Max reconnection attempts (10) reached
```

The WebSocket connected but was immediately closed. This pointed to authentication.

#### Phase 2: Authentication Mismatch

**Investigation:** Examined `security.py` (TokenAuthMiddleware):

```python
def get_token(self, scope: Scope) -> str | None:
    if scope["type"] == "websocket":
        # For WebSockets, token must be in query params  ← KEY FINDING!
        query_string = scope.get("query_string", b"").decode()
        params = dict(param.split("=") for param in query_string.split("&") if "=" in param)
        return params.get("token")
```

**But the client** (`mcpClient.ts`) was sending token in headers:
```typescript
const headers: { [key: string]: string } = {};
if (this.sessionToken) {
  headers['X-MCP-Token'] = this.sessionToken;  // ← This doesn't work for WebSocket!
}
```

**The Fix:** Append token as query parameter:
```typescript
let wsUrl = url;
if (this.sessionToken) {
  const separator = url.includes('?') ? '&' : '?';
  wsUrl = `${url}${separator}token=${encodeURIComponent(this.sessionToken)}`;
}
```

#### Phase 3: Finding the Right Cell Selectors

**Symptom:** Playwright couldn't find code cells.

**Investigation:** Added DOM inspection to the test:
```typescript
const cellClasses = await page.evaluate(() => {
  const possibleCells = document.querySelectorAll('[class*="cell"], [class*="Cell"]');
  return Array.from(possibleCells).map(el => el.className);
});
console.log('Potential cell elements:', cellClasses);
```

**Discovery:** VS Code uses `.monaco-list-row.code-cell-row`, not `.cell-editor-container`.

---

## Critical Bug Fixes

### Fix 1: WebSocket Authentication (CRITICAL)

**File:** `vscode-extension/src/mcpClient.ts`  
**Lines:** ~361

**Before:**
```typescript
this.ws = new WebSocket(url, ['mcp'], { headers, agent });
```

**After:**
```typescript
// [SECURITY FIX] Append token as query parameter for WebSocket auth
let wsUrl = url;
if (this.sessionToken) {
  const separator = url.includes('?') ? '&' : '?';
  wsUrl = `${url}${separator}token=${encodeURIComponent(this.sessionToken)}`;
}

this.ws = new WebSocket(wsUrl, ['mcp'], { headers, agent });
```

**Why This Matters:** The Starlette `TokenAuthMiddleware` only extracts tokens from query parameters for WebSocket connections, not headers. This is a common pattern because WebSocket upgrade requests have limited header support in some environments.

### Fix 2: Print Statement Flushing

**File:** `tools/mcp-server-jupyter/src/main.py`  
**Lines:** ~2846

**Before:**
```python
print(f"[MCP_PORT]: {actual_port}", file=sys.stderr)
```

**After:**
```python
print(f"[MCP_PORT]: {actual_port}", file=sys.stderr, flush=True)
```

**Why This Matters:** Python buffers stderr when it's not a TTY (which is the case when spawned by the extension). Without `flush=True`, the port number might not be immediately visible to the parent process parsing stderr.

### Fix 3: Socket Backlog

**File:** `tools/mcp-server-jupyter/src/main.py`  
**Lines:** ~2842

**Before:**
```python
sock.listen(1)
```

**After:**
```python
sock.listen(100)
```

**Why This Matters:** A backlog of 1 means only 1 pending connection can be queued. If multiple connections arrive simultaneously (or if there's any delay in accepting), connections get refused.

### Fix 4: QuickStartWizard Configuration

**File:** `vscode-extension/src/quickStartWizard.ts`  
**Lines:** ~37

**Before:**
```typescript
public showIfNeeded(): void {
  const isSetupComplete = this.context.globalState.get('mcp.hasCompletedSetup', false);
  // ...
}
```

**After:**
```typescript
public showIfNeeded(): void {
  const config = vscode.workspace.getConfiguration('mcp-jupyter');
  const showWizard = config.get<boolean>('showSetupWizard', true);
  
  if (!showWizard) {
    return;  // Respect the setting!
  }
  // ...
}
```

**Why This Matters:** For demo environments, we set `mcp-jupyter.showSetupWizard: false` but this was being ignored, causing unwanted auto-installation attempts.

### Fix 5: Playwright Cell Selectors

**File:** `scripts/demo-recording/demo-tests/duckdb-magic.spec.ts`  
**Lines:** ~130

**Before:**
```typescript
const cellSelectors = [
  '.cell-editor-container',
  '.cell-editor',
  // ...
];
```

**After:**
```typescript
const cellSelectors = [
  '.monaco-list-row.code-cell-row',     // VS Code code cell row
  '.monaco-list-row.notebook-cell-row', // Alternative row class
  '.cell-list-container .monaco-list-row',
  '.notebook-editor .monaco-editor',
  '.notebookOverlay .monaco-editor',
  '.monaco-editor'
];
```

**Why This Matters:** VS Code/code-server uses different class names than expected. The actual structure uses Monaco list rows for cells.

---

## Docker Environment Setup

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Container                          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   code-server                         │   │
│  │  ┌────────────────┐  ┌─────────────────────────────┐ │   │
│  │  │ Jupyter Ext    │  │    MCP Agent Kernel Ext     │ │   │
│  │  └────────────────┘  └──────────────┬──────────────┘ │   │
│  │                                      │                │   │
│  │                      ┌───────────────▼────────────┐   │   │
│  │                      │  MCP Python Server         │   │   │
│  │                      │  (WebSocket on port 3000+) │   │   │
│  │                      └────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Volumes:                                                    │
│  - /config/workspace/demo.ipynb (read-only)                 │
│  - /config/extensions/ (persistent)                         │
│  - /config/data/ (persistent)                               │
└──────────────────────────────────────────────────────────────┘
         │
         │ Port 8443
         ▼
┌─────────────────────┐
│  Playwright Browser │
│  (Chromium)         │
└─────────────────────┘
```

### Files Structure

```
scripts/demo-recording/
├── Dockerfile                    # Custom image with Python deps
├── docker-compose.yml           # Container orchestration
├── automation-config/
│   └── settings.json            # VS Code settings (no wizard, etc.)
├── demo-tests/
│   └── duckdb-magic.spec.ts     # Playwright test
├── demo-recordings/             # Output screenshots/videos
├── PROGRESS_PLAN_ADVERTISING_MATERIAL_TUTORIALS.md
└── LESSONS_LEARNED.md           # This file!
```

### Key Configuration

#### settings.json (Critical Settings)

```json
{
  "workbench.startupEditor": "none",           // No welcome page
  "security.workspace.trust.enabled": false,   // No trust prompts
  "mcp-jupyter.pythonPath": "/config/data/User/globalStorage/warshawsky-research.mcp-agent-kernel/mcp-venv/bin/python",
  "mcp-jupyter.showSetupWizard": false,        // No auto-install wizard
  "mcp-jupyter.autoStart": false               // Manual start for predictability
}
```

---

## Playwright Test Architecture

### Test Flow

```
1. Navigate to http://localhost:8443/?folder=/config/workspace
2. Wait for VS Code workbench (.monaco-workbench)
3. Wait 5s for extensions to initialize
4. Open notebook via Quick Open (Ctrl+P → demo.ipynb)
5. Wait for notebook editor to appear
6. Check for kernel selection prompt (handle if needed)
7. Find and click code cell (using fallback selectors)
8. Execute cell with Shift+Enter
9. Wait for output and capture screenshot
```

### Selector Strategy (Fallback Chain)

The test tries multiple selectors in order:

```typescript
const cellSelectors = [
  '.monaco-list-row.code-cell-row',     // Most specific
  '.monaco-list-row.notebook-cell-row',
  '.cell-list-container .monaco-list-row',
  '.notebook-editor .monaco-editor',
  '.notebookOverlay .monaco-editor',
  '.monaco-editor'                       // Most generic
];
```

If all fail, it attempts keyboard-only execution:
```typescript
await page.keyboard.press('Control+Home');  // Go to top
await page.keyboard.press('Shift+Enter');   // Run cell
```

---

## VS Code Extension Insights

### Extension Path Resolution

**Problem:** When TypeScript compiles to `out/src/`, `__dirname` points to incorrect location.

**Solution:**
```typescript
// In compiled output, __dirname is /extension/out/src/
// We need to go up TWO levels to get to /extension/
const extensionPath = path.dirname(path.dirname(__dirname));
```

### MCP Server Startup Sequence

1. Extension spawns Python process
2. Python writes `[MCP_SESSION_TOKEN]: xxx` to stderr
3. Python writes `[MCP_PORT]: xxx` to stderr
4. Extension parses these and connects WebSocket
5. Extension sends `initialize` JSON-RPC request
6. Server responds with capabilities
7. Extension sends `notifications/initialized`
8. Ready!

**Critical:** The `flush=True` on print statements ensures these markers are immediately available.

---

## Quick Reference Commands

### Full Environment Reset

```bash
cd scripts/demo-recording

# Stop and remove everything
docker compose down -v

# Rebuild image (if Dockerfile changed)
docker compose build --no-cache

# Start container
docker compose up -d

# Install core extensions
docker exec demo-code-server /app/code-server/bin/code-server \
  --install-extension ms-toolsai.jupyter \
  --install-extension ms-python.python

# Install MCP extension (from local build)
cd ../../vscode-extension
npm run bundle-python && npm run compile && npm run build:renderer && npx vsce package
rm -rf /tmp/mcp-ext && mkdir -p /tmp/mcp-ext && unzip -q mcp-agent-kernel-*.vsix -d /tmp/mcp-ext
docker exec demo-code-server rm -rf /config/extensions/warshawsky-research.mcp-agent-kernel-0.1.0
docker cp /tmp/mcp-ext/extension demo-code-server:/config/extensions/warshawsky-research.mcp-agent-kernel-0.1.0

# Restart to load extensions
cd ../scripts/demo-recording
docker compose restart

# Wait 10s for startup, then run test
sleep 10
npx playwright test demo-tests/duckdb-magic.spec.ts --timeout=120000
```

### Quick Test Run

```bash
cd /home/david/personal/mcp-server-jupyter/advertising-tutorials
npx playwright test scripts/demo-recording/demo-tests/duckdb-magic.spec.ts \
  --config=scripts/demo-recording/playwright.demo.config.ts \
  --timeout=120000
```

### View Logs

```bash
# MCP server logs
docker exec demo-code-server find /config/data/logs -name "1-MCP Jupyter Server.log" -exec cat {} \;

# Extension host logs  
docker exec demo-code-server cat /config/data/logs/*/exthost1/remoteexthost.log | tail -100

# Python process check
docker exec demo-code-server ps aux | grep python
```

### Manual Browser Access

Open http://localhost:8443 in browser to manually inspect the environment.

---

## Troubleshooting Guide

### "WebSocket closed: 1006"

**Cause:** Authentication failure  
**Check:** 
1. Token being parsed from stderr: `grep MCP_SESSION_TOKEN` in logs
2. Token being sent as query param in WebSocket URL
3. Middleware receiving and validating token

**Fix:** Ensure token is appended as `?token=XXX` not sent in headers.

### "Starting MCP Jupyter server..." never completes

**Cause:** Python server not printing port in time  
**Check:**
```bash
docker exec demo-code-server ps aux | grep python
```

**Fix:** Add `flush=True` to all stderr prints in main.py.

### Cell selectors not matching

**Cause:** VS Code DOM structure varies by version  
**Check:** Add this to your test:
```typescript
const cellClasses = await page.evaluate(() => {
  const cells = document.querySelectorAll('[class*="cell"]');
  return Array.from(cells).map(el => `${el.tagName}.${el.className}`);
});
console.log(cellClasses);
```

**Fix:** Update selectors based on actual DOM structure.

### Extensions not loading

**Cause:** Volume permissions or corrupt extension  
**Fix:**
```bash
docker compose down -v  # Remove volumes
docker compose up -d    # Fresh start
# Reinstall extensions...
```

### "Failed to reconnect after multiple attempts"

**Cause:** Server crashed or socket backlog exhausted  
**Check:**
```bash
docker exec demo-code-server cat /tmp/mcp_boot.log  # If debug logging enabled
```

**Fix:** Increase socket backlog, check for Python exceptions.

---

## Key Takeaways

### 1. WebSocket Auth is Different

WebSocket connections don't reliably support custom headers in all environments. **Always use query parameters for WebSocket authentication**.

### 2. Print Buffering Matters

When spawning subprocesses, stdout/stderr are often block-buffered. **Always use `flush=True`** when the parent needs to read output immediately.

### 3. DOM Inspection is Essential

VS Code's DOM structure varies. **Never hardcode selectors** - use fallback chains and runtime inspection.

### 4. Config Settings Can Be Ignored

VS Code extension settings need explicit checks. **Always verify config reads** are actually happening.

### 5. Docker Volumes Can Hide Issues

Persistent volumes can contain stale data. **Use `docker compose down -v`** for true fresh starts.

---

## Appendix: Full File Diffs

All changes are tracked in git. Key files modified:

- `vscode-extension/src/mcpClient.ts` - WebSocket auth fix
- `vscode-extension/src/quickStartWizard.ts` - Config check
- `tools/mcp-server-jupyter/src/main.py` - Print flushing, socket backlog
- `scripts/demo-recording/demo-tests/duckdb-magic.spec.ts` - Cell selectors

---

*Document generated: 2026-01-22*
