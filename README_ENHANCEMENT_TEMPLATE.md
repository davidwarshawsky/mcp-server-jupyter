# README.md Enhancement Template

## Suggested Additions to README.md

### 1. Add Quick Start Section (After Title)

```markdown
## 🚀 Quick Start (30 Seconds)

1. **Install the Extension**
   - Open VS Code Extensions (`Ctrl+Shift+X` / `Cmd+Shift+X`)
   - Search for "MCP Agent Kernel"
   - Click Install

2. **Open a Notebook**
   - Create or open a `.ipynb` file

3. **Follow the Setup Wizard**
   - The wizard opens automatically on first run
   - Select "Managed Environment" (recommended)
   - Click through the 3 steps

4. **Run Your First Cell!**
   - Select "MCP Agent Kernel" as the notebook kernel
   - Add code: `print("Hello, MCP!")`
   - Press `Shift+Enter` to execute

![Setup Wizard Demo](assets/setup-wizard.gif)
```

### 2. Add Offline Installation Section

```markdown
## 📦 Offline Installation (Enterprise/Air-Gapped)

For environments without internet access or corporate firewalls:

### Download the Fat VSIX
1. Go to [Releases](https://github.com/your-repo/releases)
2. Download `mcp-agent-kernel-<version>-fat.vsix`

### Install
```bash
# Via Command Palette
# Ctrl+Shift+P → "Extensions: Install from VSIX..."

# Or via command line
code --install-extension mcp-agent-kernel-1.0.0-fat.vsix
```

### Verify Offline Installation
The setup wizard will show:
```
Installing MCP Server Dependencies (Offline Mode)
Using bundled dependencies (offline install)
```

**No PyPI access required!** ✅

See [Fat VSIX Guide](FAT_VSIX_GUIDE.md) for details.
```

### 3. Add Troubleshooting Section

```markdown
## 🔧 Troubleshooting

### "Out of Sync" CodeLens

**Symptom:** Orange `$(alert) MCP: Out of Sync` appears at top of notebook

**Cause:** Notebook file was edited externally (e.g., git pull, manual edit)

**Fix:**
1. Click the CodeLens → syncs automatically
2. Or: Status bar → Click "⚠ 1 notebook out of sync"
3. Or: Command Palette → "MCP Jupyter: Sync Notebook from Disk"

---

### Connection Issues (🔴 Red Status Bar)

**Symptom:** Status bar shows `🔴 MCP` with red background

**Causes & Fixes:**

#### Server Crashed
1. Click status bar → "Show Logs"
2. Check "MCP Jupyter Server" output for errors
3. Click "Restart Server" in dialog

#### Python Not Found
1. Open Setup Wizard: `Ctrl+Shift+P` → "MCP Jupyter: Open Setup Wizard"
2. Complete Step 1: Select "Managed Environment"
3. The wizard installs Python automatically

#### Port Conflict
1. Check if another process is using the port:
   ```bash
   # Linux/macOS
   lsof -i :3000
   
   # Windows
   netstat -ano | findstr :3000
   ```
2. Kill the conflicting process or restart VS Code

---

### Server Won't Start

**Error:** "Failed to start MCP server: ..."

**Debug Steps:**
1. **Check Python Version:**
   ```bash
   python --version  # Should be 3.9+
   ```

2. **Check Dependencies:**
   ```bash
   pip list | grep mcp-server-jupyter
   ```

3. **Manual Test:**
   ```bash
   python -m src.main --transport websocket --port 3000
   ```

4. **View Logs:**
   - Command Palette → "MCP Jupyter: Show Server Logs"
   - Look for `ERROR` or `CRITICAL` messages

**Still stuck?** Open an [issue](https://github.com/your-repo/issues) with:
- OS and Python version
- Output of "Show Server Logs"
- Steps to reproduce

---

### Variable Dashboard Empty

**Symptom:** Variable dashboard shows no variables after running cells

**Fix:**
1. Check connection: Status bar should show `🟢 MCP`
2. Manually refresh: Click refresh icon in Variable Dashboard
3. Verify cell executed: Check for output/execution count

---

### Kernel Dies During Execution

**Symptom:** Cell execution stops mid-run, kernel status shows "Dead"

**Causes:**
- Out of memory (large datasets)
- Segmentation fault in native library (numpy, pandas)
- User interrupted with `Ctrl+C` multiple times

**Fix:**
1. Restart kernel: `Ctrl+Shift+P` → "Notebook: Restart Kernel"
2. Check memory usage: Task Manager / Activity Monitor
3. Reduce dataset size or use generators

---

### Extension Activation Failed

**Error:** Toast notification shows activation error

**Fix:**
1. Reload VS Code: `Ctrl+Shift+P` → "Developer: Reload Window"
2. Check VS Code version: Help → About (should be 1.85.0+)
3. Reinstall extension:
   ```bash
   code --uninstall-extension warshawsky-research.mcp-agent-kernel
   code --install-extension warshawsky-research.mcp-agent-kernel
   ```
```

### 4. Add Features Section with Screenshots

```markdown
## ✨ Features

### 🧙 AI-Powered Kernel Management
- Automatic Python environment detection
- Smart dependency installation
- Kernel lifecycle management

### 🔄 Real-Time Sync Detection
Inline CodeLens shows sync status:
- `$(sync) MCP: Synced` - All good!
- `$(alert) MCP: Out of Sync` - Click to fix

![Sync CodeLens](assets/sync-codelens.png)

### 📊 Variable Dashboard
2-second live polling of notebook variables:
- See all variables at a glance
- Auto-updates as you run cells
- Supports pandas DataFrames, NumPy arrays

![Variable Dashboard](assets/variable-dashboard.png)

### 🟢 Connection Health Indicator
Always know the server status:
- 🟢 Connected and ready
- 🟡 Connecting (animated)
- 🔴 Disconnected (click for help)

![Status Bar](assets/status-bar.png)

### 🗑️ Automatic Asset Cleanup
Garbage collection removes orphaned output files:
- Deletes assets when cells are cleared
- Triggered automatically on save
- Keeps workspace clean

### 🔒 Secure by Default
- Pydantic validation on all inputs
- Structured logging (JSON)
- Fatal exception handler
- Thread pool for heavy operations
```

### 5. Add Configuration Section

```markdown
## ⚙️ Configuration

### Extension Settings

Access via: `File → Preferences → Settings` → Search "MCP Jupyter"

| Setting | Default | Description |
|---------|---------|-------------|
| `mcp-jupyter.serverMode` | `spawn` | Server mode: `spawn` (managed) or `connect` (external) |
| `mcp-jupyter.pythonPath` | *(auto)* | Path to Python interpreter (set by wizard) |
| `mcp-jupyter.remotePort` | `3000` | Port for `connect` mode |
| `mcp-jupyter.autoRestart` | `true` | Auto-restart server on crash |
| `mcp-jupyter.idleTimeout` | `600` | Idle timeout in seconds (0 = never) |

### Connect Mode (Advanced)

For running the server separately:

1. **Start Server Manually:**
   ```bash
   cd tools/mcp-server-jupyter
   python -m src.main --transport websocket --port 3000
   ```

2. **Configure Extension:**
   ```json
   {
     "mcp-jupyter.serverMode": "connect",
     "mcp-jupyter.remotePort": 3000
   }
   ```

3. **Reload Window:** `Ctrl+Shift+P` → "Developer: Reload Window"

**Use Case:** Debugging server changes without reloading extension
```

### 6. Add GIF Placeholders

Create these GIFs using screen recording:

1. **setup-wizard.gif** (30s)
   - Show extension activation
   - Walkthrough opening automatically
   - Completing 3 steps
   - First cell execution

2. **sync-codelens.png** (screenshot)
   - Notebook with "Out of Sync" CodeLens
   - Before and after clicking

3. **variable-dashboard.png** (screenshot)
   - Dashboard with sample variables
   - Show refresh button

4. **status-bar.png** (screenshot)
   - Three states: 🟢🟡🔴

**Tool Recommendation:** Use [ScreenToGif](https://www.screentogif.com/) (Windows/Linux) or [Kap](https://getkap.co/) (macOS)

---

## Implementation

1. **Open README.md** in the extension folder
2. **Insert sections** in this order:
   - Quick Start (after title/badges)
   - Features (with placeholders for images)
   - Offline Installation (in Installation section)
   - Configuration (new section)
   - Troubleshooting (before Contributing)

3. **Create placeholder GIFs:**
   ```bash
   mkdir -p assets
   # Record GIFs and save to assets/
   ```

4. **Update links:**
   - Replace `https://github.com/your-repo` with actual repo URL
   - Update issue tracker link

5. **Test locally:**
   ```bash
   # Preview in VS Code
   code README.md
   # Then: Ctrl+Shift+V (preview mode)
   ```

---

## Before/After Example

### Current README (Likely)
```markdown
# MCP Agent Kernel

A VS Code extension for MCP-powered Jupyter notebooks.

## Installation
Install from VSIX or Marketplace.

## Usage
Open a notebook and select MCP Agent Kernel.
```

### Enhanced README
```markdown
# MCP Agent Kernel

> AI-powered Jupyter notebook execution in VS Code

[![Version](badge-url)](link) [![Downloads](badge-url)](link)

## 🚀 Quick Start (30 Seconds)
[GIF here]
[Step-by-step instructions]

## ✨ Features
[Screenshots with descriptions]

## 📦 Installation

### Standard (Online)
[Instructions]

### Offline / Air-Gapped
[Instructions with Fat VSIX link]

## ⚙️ Configuration
[Settings table]

## 🔧 Troubleshooting
[Common issues with fixes]

## 🤝 Contributing
[Link to CONTRIBUTING.md]
```

**Impact:** Users can start using the extension in 30 seconds instead of 5 minutes of trial-and-error.
