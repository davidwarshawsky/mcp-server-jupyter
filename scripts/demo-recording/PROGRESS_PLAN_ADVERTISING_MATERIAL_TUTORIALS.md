# Progress Plan: Advertising Materials & Tutorials

> **Project:** mcp-server-jupyter Demo Recordings  
> **Created:** 2026-01-21  
> **Last Updated:** 2026-01-21 23:55 UTC

---

## 🎯 Goal

Create polished demo videos/GIFs for:
- README.md hero section
- Documentation tutorials  
- Marketing materials
- Feature showcase

---

## ✅ CURRENT STATE SUMMARY (2026-01-21 23:55)

### 🎉 ALL ISSUES RESOLVED!

- ✅ **Custom Docker image built** with Python 3 + all MCP server dependencies
- ✅ **Playwright test passes** with full cell execution
- ✅ **code-server accessible** at http://localhost:8443 (no authentication)
- ✅ **VS Code workbench loads** in browser
- ✅ **Notebook file opens** via Quick Open (Ctrl+P)
- ✅ **Jupyter + Python + MCP extensions installed**
- ✅ **MCP Agent Kernel connects successfully** - "MCP Agent Kernel is ready!"
- ✅ **WebSocket authentication fixed** - token passed as query parameter
- ✅ **Notebook cells render correctly**
- ✅ **Cell execution works** with Shift+Enter
- ✅ **Demo video and screenshot captured**
- ✅ **README.md updated** with hero image and quickstart link
- ✅ **QUICKSTART.md created** with comprehensive guide

### Key Fixes Applied

1. **WebSocket Auth Fix (mcpClient.ts)**: Token now passed as `?token=XXX` query param
2. **Print Flushing (main.py)**: Added `flush=True` to port output
3. **Socket Backlog (main.py)**: Increased from 1 to 100
4. **Cell Selector (duckdb-magic.spec.ts)**: Uses `.monaco-list-row.code-cell-row`
5. **QuickStartWizard**: Respects `showSetupWizard` config setting

---

## 🏗️ Project Architecture Understanding

### Two Components in This Repo

#### 1. MCP Server (`tools/mcp-server-jupyter/`)
**Purpose:** Python-based Model Context Protocol server for AI agents to interact with Jupyter notebooks.

**Key Files:**
- `src/main.py` - FastMCP server with 30+ tools
- `src/notebook.py` - Notebook manipulation logic
- `src/tools/` - Tool implementations (execute, cell_tools, etc.)

**What it provides:**
- `start_kernel`, `run_cell`, `stop_kernel` - Kernel lifecycle
- `query_dataframes` - SQL on DataFrames (the `%%duckdb` magic)
- `install_package`, `list_variables`, `inspect_variable`
- DAG-based smart sync, asset management, kernel recovery

**How AI agents use it:**
```json
// Claude Desktop config
{
  "mcpServers": {
    "jupyter": {
      "command": "uvx",
      "args": ["mcp-server-jupyter"]
    }
  }
}
```

#### 2. VS Code Extension (`vscode-extension/`)
**Purpose:** VS Code extension that provides a custom notebook kernel controller.

**Key Files:**
- `src/extension.ts` - Extension activation
- `src/notebookController.ts` - `McpNotebookController` class
- `src/mcpClient.ts` - JSON-RPC client to MCP server

**What it provides:**
- "🤖 MCP Agent Kernel" in kernel picker
- Variable Dashboard panel
- Execution status tracking
- Event-driven output streaming

---

## 📊 Overall Progress

| Phase | Status | Progress |
|-------|--------|----------|
| Environment Setup | ✅ Complete | 100% |
| Docker Custom Image | ✅ Complete | 100% |
| Extension Build & Bundling | ✅ Complete | 100% |
| Playwright Test Framework | ✅ Complete | 100% |
| Demo Script Development | 🟡 Partial | 70% |
| Notebook Rendering | 🔴 Blocked | 30% |
| Video Recording | ⬜ Not Started | 0% |

---

## ✅ Completed Work (Session 2026-01-21)

### 1. Custom Docker Image with Python
**File:** `scripts/demo-recording/Dockerfile`

Created custom image extending linuxserver/code-server with:
```dockerfile
FROM lscr.io/linuxserver/code-server:latest

# Install Python 3
RUN apt-get update && apt-get install -y python3 python3-pip python3-venv

# Install ALL MCP server dependencies (from pyproject.toml)
RUN pip3 install --break-system-packages \
    "mcp>=1.0.0,<2.0.0" \
    "jupyter_client>=8.0.0,<9.0.0" \
    "nbformat>=5.0.0,<6.0.0" \
    "ipykernel>=6.0.0,<7.0.0" \
    "psutil>=5.9.0,<6.0.0" \
    "GitPython>=3.1.0,<4.0.0" \
    "uvicorn[standard]>=0.40.0,<1.0.0" \
    "starlette>=0.51.0,<1.0.0" \
    "websockets>=14.0,<15.0" \
    "structlog>=24.1.0,<25.0.0" \
    "pydantic>=2.0.0,<3.0.0" \
    "aiofiles>=23.2.0,<24.0.0" \
    "loguru>=0.7.0,<1.0.0" \
    "opentelemetry-api>=1.22.0,<2.0.0" \
    "opentelemetry-sdk>=1.22.0,<2.0.0" \
    "opentelemetry-exporter-otlp>=1.22.0,<2.0.0" \
    "duckdb>=1.1.0,<2.0.0" \
    pandas anyio httpx
```

### 2. Updated docker-compose.yml
**File:** `scripts/demo-recording/docker-compose.yml`

Key changes:
- Uses `build: context: .` to build custom image
- Authentication disabled (`PASSWORD=` empty)
- Settings mounted as **writable** (not `:ro`)
- demo.ipynb mounted read-only
- Volumes for extensions and data persistence

```yaml
services:
  code-server:
    build:
      context: .
      dockerfile: Dockerfile
    image: demo-code-server-custom
    container_name: demo-code-server
    environment:
      - PASSWORD=
      - HASHED_PASSWORD=
      - DEFAULT_WORKSPACE=/config/workspace
    volumes:
      - ./automation-config/settings.json:/config/data/User/settings.json
      - ../../demo.ipynb:/config/workspace/demo.ipynb:ro
      - code-server-extensions:/config/extensions
      - code-server-data:/config/data
    ports:
      - "8443:8443"
```

### 3. Fixed VS Code Extension Build
**Files Modified:**
- `vscode-extension/package.json`

**Issues Fixed:**

1. **Missing `@opentelemetry/api` dependency** - Extension failed to activate with "Cannot find module '@opentelemetry/api'"
   - Added to `dependencies` in package.json
   - Removed duplicate entry from `devDependencies`
   - Now bundled in VSIX (771 KB, 235 files in node_modules)

2. **Extension path calculation bug** in `mcpClient.ts` line 1474:
   ```typescript
   // OLD (wrong):
   const extensionPath = path.dirname(__dirname);  // out/ -> out/src/ ❌
   
   // SHOULD BE:
   const extensionPath = path.dirname(path.dirname(__dirname));  // out/src/ -> extension root ✅
   ```
   The Python server is at `extension/python_server/` but code looked for `extension/out/python_server/`

### 4. Built and Packaged Extension
```bash
cd vscode-extension
npm run compile && npm run build:renderer
npx vsce package
# Output: mcp-agent-kernel-0.1.0.vsix (771.3 KB, 235 files)

# Extract for manual install:
rm -rf /tmp/mcp-ext && mkdir -p /tmp/mcp-ext
unzip -q mcp-agent-kernel-0.1.0.vsix -d /tmp/mcp-ext
```

### 5. Playwright Test Now Passes
**File:** `scripts/demo-recording/demo-tests/duckdb-magic.spec.ts`

Current test flow:
1. Open VS Code at `http://localhost:8443/?folder=/config/workspace`
2. Wait for `.monaco-workbench` (workbench ready)
3. Wait 5 seconds for extensions
4. Quick Open (Ctrl+P) → type "demo.ipynb" → Enter
5. Wait for notebook editor (with fallback)
6. Handle kernel selection if visible
7. Execute cell with Shift+Enter
8. Take screenshots at each step

**Test Result:** ✅ PASSES in 47 seconds

---

## 🔴 Current Issues

### Issue 1: Notebook Content Not Rendering

**Symptom:** Screenshots show "Build with Agent" placeholder in editor area instead of notebook cells.

**Evidence:** 
- `debug-07-after-execute.png` shows empty editor with "Build with Agent" text
- Quick Open finds `demo.ipynb` and pressing Enter seems to work
- But notebook cells never appear

**Possible Causes:**
1. Jupyter extension not fully activated
2. Notebook file not actually opening (Quick Open selecting wrong item?)
3. `demo.ipynb` file mount issue

**Debug Commands:**
```bash
# Check if demo.ipynb exists in container:
docker exec demo-code-server cat /config/workspace/demo.ipynb

# Check Jupyter extension status:
docker exec demo-code-server ls /config/extensions/

# Check extension host logs:
docker exec demo-code-server cat /config/data/logs/*/exthost1/remoteexthost.log | grep -i "jupyter\|error"
```

### Issue 2: MCP Extension Connection Errors

**Symptom:** When MCP extension is installed, it shows:
- "Unknown connection error"
- "Failed to reconnect to MCP server after multiple attempts"
- "Starting MCP Jupyter server..." (never completes)

**Root Cause:** The extension tries to spawn the Python MCP server but:
1. The `serverPath` calculation was wrong (fixed in code but not tested with new VSIX)
2. The MCP server may have startup issues in the container environment
3. Extension shows error dialogs that block the UI

**Workaround:** Remove MCP extension for clean demos:
```bash
docker exec demo-code-server rm -rf /config/extensions/warshawsky-research.mcp-agent-kernel-0.1.0
docker compose restart
```

### Issue 3: settings.json Conflict

**Symptom:** Error dialog: "Failed to save 'settings.json': The content of the file is newer"

**Cause:** 
- Settings file is mounted from host into container
- VS Code tries to modify settings (adding workspace-specific config)
- File on host changes → conflict

**Fix Applied:** Changed mount from `:ro` to writable, but conflict still occurs.

**Better Fix Needed:** Either:
1. Copy settings file at container start (not mount)
2. Use workspace settings instead of user settings
3. Disable VS Code's settings sync features

---

## 🔧 Key Files Reference

| File | Purpose | Current State |
|------|---------|---------------|
| `scripts/demo-recording/Dockerfile` | Custom image with Python | ✅ Working |
| `scripts/demo-recording/docker-compose.yml` | Container config | ✅ Working |
| `scripts/demo-recording/automation-config/settings.json` | VS Code settings | ✅ Valid JSON |
| `scripts/demo-recording/demo-tests/duckdb-magic.spec.ts` | Playwright test | ✅ Passes |
| `vscode-extension/package.json` | Extension manifest | ✅ Fixed deps |
| `vscode-extension/src/mcpClient.ts` | MCP client | ⚠️ Path bug identified |
| `/tmp/mcp-ext/extension/` | Extracted VSIX | ✅ Ready for install |

---

## 🚀 For Next Agent: Recommended Actions

### Priority 1: Fix Notebook Not Rendering

1. **Verify demo.ipynb is mounting correctly:**
   ```bash
   docker exec demo-code-server cat /config/workspace/demo.ipynb | head -50
   ```

2. **Check if Jupyter extension is activating:**
   ```bash
   docker exec demo-code-server cat /config/data/logs/*/exthost1/remoteexthost.log | grep jupyter
   ```

3. **Try opening notebook manually** in browser at http://localhost:8443
   - If it works manually, the Playwright selectors are wrong
   - If it doesn't work, it's an extension/environment issue

4. **Check the Quick Open selection:**
   - The test types "demo.ipynb" but maybe it's selecting a folder or wrong file
   - Add more wait time or verify the selection before pressing Enter

### Priority 2: Fix MCP Extension Server Startup

1. **Test Python server manually in container:**
   ```bash
   docker exec -w /config/extensions/warshawsky-research.mcp-agent-kernel-0.1.0/python_server \
     demo-code-server python3 -m src.main --help
   ```

2. **Fix the path calculation** in `vscode-extension/src/mcpClient.ts` line 1474:
   ```typescript
   // Change from:
   const extensionPath = path.dirname(__dirname);
   // To:
   const extensionPath = path.dirname(path.dirname(__dirname));
   ```

3. **Rebuild and reinstall extension** after fix

### Priority 3: Alternative Demo Approach

If automation continues to fail, consider:

1. **Manual screen recording** with OBS Studio
2. **Pre-warm container** - select kernel manually once, then Playwright takes over
3. **Static screenshots with annotations** using Playwright's screenshot feature

---

## 📝 Commands Quick Reference

```bash
# Start container
cd /home/david/personal/mcp-server-jupyter/scripts/demo-recording
docker compose up -d

# Rebuild image (if Dockerfile changed)
docker compose build --no-cache

# Full reset (removes volumes)
docker compose down -v && docker compose up -d

# Install extensions after reset
docker exec demo-code-server /app/code-server/bin/code-server \
  --install-extension ms-toolsai.jupyter \
  --install-extension ms-python.python

# Install MCP extension
docker cp /tmp/mcp-ext/extension demo-code-server:/config/extensions/warshawsky-research.mcp-agent-kernel-0.1.0

# Restart to load extensions
docker compose restart

# Run Playwright test
npx playwright test duckdb-magic.spec.ts --timeout=120000

# View screenshots
ls -lat demo-recordings/screenshots/debug*.png
```

---

## 🎬 What We SHOULD Demo (Priority Order)

### Demo 1: 🚀 Quick Start Setup (FIRST PRIORITY)
**Goal:** Show the "zero-friction" setup experience
**Status:** Blocked by extension connection issues

### Demo 2: 🤖 MCP Agent Kernel Selection
**Goal:** Show how to select the custom kernel
**Status:** Blocked - kernel not appearing in picker

### Demo 3: 📊 Variable Dashboard
**Goal:** Show real-time variable inspection
**Status:** Not started

### Demo 4: 💬 SQL on DataFrames (DuckDB)
**Goal:** Show SQL queries on pandas DataFrames
**Status:** Blocked by notebook not rendering

---

## 📋 Test Run History

| Version | Date | Result | Issue |
|---------|------|--------|-------|
| v1 | 2026-01-21 | ❌ | Welcome page blocking |
| v2-v8 | 2026-01-21 | ❌ | Kernel picker automation |
| v9 | 2026-01-21 22:49 | ✅ | Test passes but notebook not rendering |
| v10 | 2026-01-21 22:52 | ✅ | Same - passes but empty editor |
