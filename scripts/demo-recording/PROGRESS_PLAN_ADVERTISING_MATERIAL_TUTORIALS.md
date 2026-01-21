# Progress Plan: Advertising Materials & Tutorials

> **Project:** mcp-server-jupyter Demo Recordings  
> **Created:** 2026-01-21  
> **Last Updated:** 2026-01-21 17:45 UTC

---

## 🎯 Goal

Create polished demo videos/GIFs for:
- README.md hero section
- Documentation tutorials  
- Marketing materials
- Feature showcase

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

**How users select it:**
When opening a notebook, users see the kernel picker and can choose "🤖 MCP Agent Kernel" instead of the regular Python kernel.

### For Demo Recordings

**Question:** Do we need the custom VS Code extension for demos?

**Answer:** It depends on what we're demoing:

| Demo Type | Extension Needed? | Why |
|-----------|-------------------|-----|
| `%%duckdb` SQL magic | ❌ No | Works with standard Jupyter kernel + pandas |
| MCP Agent features | ✅ Yes | Requires `mcp-agent-kernel` extension |
| Auto-EDA, Asset Management | ✅ Yes | These are MCP server tools |

**For the current DuckDB demo:** We're showing the `%%duckdb` magic which is a cell magic that queries DataFrames. This requires:
1. A working Python kernel (standard Jupyter extension)
2. pandas + duckdb packages installed
3. **NOT** the custom MCP extension

---

## 📊 Overall Progress

| Phase | Status | Progress |
|-------|--------|----------|
| Environment Setup | ✅ Complete | 100% |
| Demo Script Development | 🔴 Blocked | 50% |
| Video Recording | ⬜ Not Started | 0% |
| Post-Processing (GIF conversion) | ⬜ Not Started | 0% |

---

## ✅ Completed Work

### 1. Docker-Based Recording Environment
- [x] Created `docker-compose.yml` with linuxserver/code-server
- [x] Configured isolated container (won't kill live VS Code sessions)
- [x] Mounted workspace at `/config/workspace`
- [x] Created `automation-config/settings.json` with:
  - Welcome page disabled
  - Workspace trust disabled
  - Extension recommendations disabled
  - Git prompts disabled

### 2. Playwright Test Infrastructure
- [x] Created `playwright.demo.config.ts`
- [x] Created `run-demo.sh` helper script
- [x] Video recording enabled (WebM format)
- [x] Screenshot capture at key steps

### 3. Extension Installation (Verified Working)
All 8 extensions confirmed in `/config/.local/share/code-server/extensions/`:
- [x] ms-toolsai.jupyter-2025.9.1
- [x] ms-toolsai.jupyter-renderers-1.3.0
- [x] ms-toolsai.jupyter-keymap-1.1.2
- [x] ms-toolsai.vscode-jupyter-cell-tags-0.1.9
- [x] ms-toolsai.vscode-jupyter-slideshow-0.1.6
- [x] ms-python.python-2026.0.0
- [x] ms-python.debugpy-2024.0.0
- [x] ms-python.vscode-python-envs-1.16.0

### 4. Python Environment in Container
- [x] Python 3.12.3 at `/usr/bin/python3`
- [x] ipykernel installed
- [x] pandas installed
- [x] Kernel registered at `/config/.local/share/jupyter/kernels/python3`
- [x] `jupyter kernelspec list` shows `python3` available

### 5. Test Script Improvements (duckdb-magic.spec.ts)
- [x] Fixed: Navigate with `?folder=` parameter
- [x] Fixed: Wait for `.monaco-workbench` and `.activitybar`
- [x] Fixed: Close Welcome tab if present
- [x] Fixed: Use Quick Open (Ctrl+P) to open notebook
- [x] Fixed: Wait for notebook editor to be ready
- [x] Fixed: Target CODE cells specifically (`.code-cell-row`)
- [x] Fixed: Use Shift+Enter to run cells
- [x] Added: Extension dialog dismissal logic

---

## 🔴 Current Blocker: Kernel Auto-Selection

### Problem Description (UPDATED 2026-01-21 17:45)

When opening a notebook and pressing Shift+Enter to execute a cell, VS Code shows:
- "Type to choose a kernel source" dropdown
- Options:
  1. "Install/Enable suggested extensions: Python + Jupyter"
  2. "Browse marketplace for kernel extensions"

Even though extensions ARE installed and the Python kernel IS registered, VS Code won't auto-select.

### Root Cause Analysis (from research)

Based on research of VS Code Jupyter issues (#130946, #13032, #16365):

1. **VS Code remembers kernel per-notebook** - But only AFTER a user manually selects once
2. **No `defaultKernel` setting exists** - Despite 113 upvotes requesting it (issue #130946)
3. **Notebook metadata is checked** - But VS Code still prompts if it can't match to a running kernel
4. **Multiple Python environments = always prompts** - VS Code can't auto-decide between them

### Why It Keeps Prompting

The notebook (`demo.ipynb`) has this metadata:
```json
{
  "kernelspec": {
    "display_name": "Python 3",
    "language": "python",
    "name": "python3"
  }
}
```

But VS Code:
1. Opens notebook → sees metadata says "python3"
2. Looks for kernel named "python3" → finds it at `/config/.local/share/jupyter/kernels/python3`
3. But **won't auto-attach** until user confirms once (security feature)
4. Shows "Select Kernel" prompt every time in a fresh container

### Potential Solutions

#### Solution A: Pre-configure kernel association (Recommended)
Store kernel selection in VS Code's workspace state:
```json
// .vscode/settings.json
{
  "python.defaultInterpreterPath": "/usr/bin/python3",
  "jupyter.kernels.filter": [{"path": "/usr/bin/python3"}]
}
```

#### Solution B: Exclude all other kernels
Force single kernel by excluding alternatives:
```json
{
  "jupyter.kernels.excludePythonEnvironments": ["*"]
}
```
Then only the registered kernelspec remains.

#### Solution C: Install "Default Python Kernels" extension
Use donjayamanne's extension from marketplace that auto-selects based on settings.

#### Solution D: Automate the kernel selection in Playwright
Click through the kernel picker UI:
1. Click on "Python Environments" 
2. Click on "Python 3.12.3" entry
3. Wait for kernel to connect
4. Then execute cells

---

## 📋 Demo Specifications

### PRIORITY RE-EVALUATION (2026-01-21 18:00)

Based on codebase analysis, the kernel selection issue in code-server is a **fundamental blocker** that makes Playwright automation of notebooks extremely difficult. The issue is:

1. **VS Code/code-server requires manual kernel selection** on first run per notebook
2. This is intentional UX (security/user choice) - not a bug we can fix with settings
3. The quick-input picker has dynamic, hard-to-predict selectors

**NEW STRATEGY:** Instead of fighting with browser automation, we should:

### Option A: Screen Recording (Manual)
Record demos manually using:
- **OBS Studio** for full-quality screen capture
- **ScreenToGif** for quick GIF creation
- **asciinema** for terminal-focused demos

### Option B: Use Real VS Code (Not code-server)
The VS Code extension (`mcp-agent-kernel`) works in real VS Code. Demo:
1. Install extension from VSIX
2. Open notebook
3. Select "🤖 MCP Agent Kernel" 
4. Execute cells

This sidesteps the kernel picker issue because:
- The MCP Agent Kernel IS the custom kernel
- No conflict with Python kernels
- One-click selection

### Option C: Pre-warm the Container
Before Playwright runs:
1. Manually select kernel once
2. Save notebook with kernel association
3. Export code-server state
4. Playwright automation now works

---

## 🎬 What We SHOULD Demo (Priority Order)

Based on codebase analysis, here's what matters to users:

### Demo 1: 🚀 Quick Start Setup (FIRST PRIORITY)
**Goal:** Show the "zero-friction" setup experience
**Duration:** 30-45 seconds
**Script:**
1. Install extension (show marketplace or `code --install-extension`)
2. Press F1 → "MCP Jupyter: Quick Start"
3. Select "Automatic Setup"
4. Watch progress indicator
5. Success toast appears
6. Open example notebook

**Why it matters:** Users want to know setup is EASY. This is the first thing they see.

### Demo 2: 🤖 MCP Agent Kernel Selection
**Goal:** Show how to select the custom kernel
**Duration:** 15-20 seconds
**Script:**
1. Open a notebook
2. Click kernel selector (top-right)
3. Choose "🤖 MCP Agent Kernel"
4. Status bar shows "MCP Connected"

**Why it matters:** This is how users ACCESS the superpowers.

### Demo 3: 📊 Variable Dashboard
**Goal:** Show real-time variable inspection
**Duration:** 20-30 seconds
**Script:**
1. Execute a cell creating a DataFrame
2. Open "MCP Variables" panel (sidebar)
3. See variables listed with types, shapes
4. Click to expand details

**Why it matters:** This is a "wow" feature - see your data without printing it.

### Demo 4: 💬 SQL on DataFrames (Future - DuckDB)
**Goal:** Show SQL queries on pandas DataFrames
**Duration:** 30 seconds
**Script:** (The demo we were trying to make)

### Demo 5: 🔄 Kernel Auto-Recovery (Future)
**Goal:** Show the Reaper recovering from kernel crash
**Duration:** 20 seconds

---

## 🚫 Current Blocker: Why Playwright + code-server Is Failing

### Root Cause
The VS Code Jupyter extension intentionally requires user confirmation to select a kernel:

1. **No `defaultKernel` setting** - Despite 113 upvotes requesting it (GitHub issue #130946)
2. **Per-notebook kernel memory** - Only persists after first manual selection  
3. **code-server starts fresh** - Container has no saved kernel associations

### Technical Details
When you try to run a cell without a kernel:
- Dialog appears: "Type to choose a kernel source"
- Options include "Python Environments", "Jupyter Kernels", "Install extensions"
- These use VS Code's `QuickPick` API with dynamic, complex selectors
- The picker has multiple levels (source → specific kernel)

### Why Automation Fails
```typescript
// This doesn't work reliably because:
await page.locator('.quick-input-list-entry:has-text("Python 3")').click();

// 1. The entry may not be visible (need to scroll)
// 2. There may be multiple matches
// 3. The picker may require clicking parent category first
// 4. Timing varies with extension loading
```

---

## 🔧 Files Modified

| File | Purpose | Status |
|------|---------|--------|
| `scripts/demo-recording/docker-compose.yml` | Container config | ✅ Working |
| `scripts/demo-recording/automation-config/settings.json` | VS Code settings | ✅ Working |
| `scripts/demo-recording/demo-tests/duckdb-magic.spec.ts` | Main test script | 🔴 Blocked |
| `scripts/demo-recording/playwright.demo.config.ts` | Playwright config | ✅ Working |
| `scripts/demo-recording/run-demo.sh` | Helper script | ✅ Working |
| `demo.ipynb` | Demo notebook | ✅ Correct format |

---

## 📝 Test Run History

| Version | Date | Result | Issue |
|---------|------|--------|-------|
| v1 | 2026-01-21 | ❌ | Welcome page blocking |
| v2 | 2026-01-21 | ❌ | Typing in search bar |
| v3 | 2026-01-21 | ❌ | Clicking markdown cell |
| v4 | 2026-01-21 | ❌ | Stuck on kernel source selection |
| v5-v8 | 2026-01-21 | ❌ | Kernel picker automation failing |

---

## 🚀 Recommended Next Actions

### Option 1: Manual Recording (Fastest)
1. Install OBS Studio or use Windows Game Bar (Win+G)
2. Open real VS Code with the extension installed
3. Record the Quick Start wizard
4. Record kernel selection
5. Record cell execution
6. Trim and export as GIF

**Time estimate:** 30 minutes to get a working demo

### Option 2: Pre-warm Docker Container
1. Manually connect to code-server (`http://localhost:8443`)
2. Open `demo.ipynb` manually
3. Select Python 3 kernel manually
4. Execute cells to verify working
5. **Don't close the container**
6. Now run Playwright (kernel already selected)

### Option 3: Use MCP Agent Kernel Instead
If we install our own extension in the container:
1. The "🤖 MCP Agent Kernel" appears as a kernel option
2. It's our own kernel, designed for notebooks
3. May be easier to auto-select

### Option 4: Create Static Demo Content
- Use screenshots with annotations
- Create animated GIFs from pre-recorded footage
- Write step-by-step guides with images

---

## 🎯 Immediate Priority

**STOP** trying to automate notebook execution with Playwright in code-server.
**START** either:
1. Recording manually (fastest to results)
2. Testing Option 2 (pre-warm container)
3. Installing MCP extension in container and demoing that
