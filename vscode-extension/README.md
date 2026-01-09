# MCP Agent Kernel - VSCode Extension

A VSCode extension that provides a Jupyter notebook kernel powered by the MCP (Model Context Protocol) server, enabling seamless collaboration between human developers and AI agents.

## 🎯 What is This?

This extension acts as a "Proxy Kernel" for Jupyter notebooks in VSCode. Instead of managing kernels directly, it routes all cell execution through an MCP server, allowing both you and AI agents to share the same kernel state, execution queue, and notebook file.

**Key Benefits:**
- **Shared State**: Human and AI agent see the same variables, outputs, and execution history
- **Handoff Protocol**: Automatic detection and sync when switching between human and AI control
- **Environment Management**: Easy switching between conda/venv/system Python environments
- **Real-time Streaming**: See outputs appear incrementally during long-running computations
- **Zero Lock-in**: Works with standard `.ipynb` files - no proprietary formats

## 🚀 Features

### ✅ Core Functionality
- **Jupyter Notebook Support**: Execute Python code in `.ipynb` files
- **Incremental Output Streaming**: See print statements and outputs as they happen
- **Environment Selection**: Quick-pick UI to switch Python environments (conda, venv, system)
- **Automatic Kernel Management**: Kernels start on-demand and stop when notebooks close
- **Error Handling**: Full traceback rendering for exceptions
- **Rich Output Support**: Text, HTML, images (PNG/JPEG), JSON, and more

### 🤝 Human ↔ AI Collaboration
- **Handoff Protocol**: Detects when notebook was edited externally (by AI or another editor)
- **Auto-Sync**: Re-executes cells to rebuild kernel state after external edits
- **Shared Execution Queue**: Both human and AI agent cell executions use the same queue
- **Provenance Tracking**: All executions tagged with metadata (timestamp, environment, tool)

### 🔧 Developer Experience
- **Output Channel**: View MCP server logs for debugging
- **Configurable Polling**: Adjust streaming update frequency (default: 500ms)
- **Auto-Restart**: Server automatically restarts on crash (configurable)
- **Manual Controls**: Commands to restart server, select environment, view logs

## 📦 Installation

### Prerequisites
1. **VSCode**: Version 1.85.0 or higher
2. **MCP Server**: The Python MCP server must be installed (sibling directory)
3. **Python**: Python 3.10+ with Jupyter dependencies

### Install Extension

#### Option 1: From Source (Development)
```bash
cd vscode-extension
npm install
npm run compile
```

Then press `F5` in VSCode to launch Extension Development Host.

#### Option 2: From VSIX (Production)
```bash
# Build VSIX package
cd vscode-extension
npm install
npm run vscode:prepublish
vsce package

# Install
code --install-extension mcp-agent-kernel-0.1.0.vsix
```

### Verify Installation
1. Open a `.ipynb` file in VSCode
2. Click the kernel picker (top-right)
3. Select **🤖 MCP Agent Kernel**
4. Run a cell: `print("Hello from MCP!")`

If you see output, you're ready!

## 🎮 Usage

### Basic Workflow

1. **Open Notebook**: Open any `.ipynb` file in VSCode
2. **Select Kernel**: Click kernel picker → **🤖 MCP Agent Kernel**
3. **Run Cells**: Press `Shift+Enter` or click ▶️ button
4. **View Outputs**: Outputs appear incrementally as code runs

### Commands

Access via Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`):

| Command | Description |
|---------|-------------|
| `MCP Jupyter: Select Python Environment` | Switch to a different Python environment |
| `MCP Jupyter: Restart Server` | Restart the MCP server process |
| `MCP Jupyter: Show Server Logs` | Open output channel with server logs |

### Configuration

Settings available in VSCode Settings (`Ctrl+,` / `Cmd+,`):

| Setting | Default | Description |
|---------|---------|-------------|
| `mcp-jupyter.serverPath` | (auto) | Path to MCP server directory |
| `mcp-jupyter.pythonPath` | (auto) | Python executable for MCP server |
| `mcp-jupyter.pollingInterval` | 500 | Polling interval (ms) for output streaming |
| `mcp-jupyter.autoRestart` | true | Auto-restart server on crash |

#### Example `.vscode/settings.json`
```json
{
  "mcp-jupyter.serverPath": "/path/to/mcp-server-jupyter",
  "mcp-jupyter.pythonPath": "/opt/conda/envs/data-science/bin/python",
  "mcp-jupyter.pollingInterval": 1000,
  "mcp-jupyter.autoRestart": true
}
```

### Environment Selection

**Automatic Detection**:
The extension automatically finds:
- Conda environments (`conda env list`)
- Virtual environments (venv)
- System Python

**Manual Selection**:
1. Open Command Palette
2. Run `MCP Jupyter: Select Python Environment`
3. Choose environment from list
4. Kernel restarts with new environment

### Handoff Protocol (Human ↔ AI Collaboration)

**Scenario**: You run cells in VSCode, then an AI agent modifies the notebook file externally.

**What Happens**:
1. You open the notebook again in VSCode
2. Extension detects file was modified since last kernel state
3. Prompts: "Syncing notebook state..."
4. Re-executes all previously executed cells to rebuild state
5. Kernel now matches disk state - you can continue where AI left off

**How It Works**:
- MCP server tracks last modification timestamp of notebook
- Compares with kernel state timestamp
- If disk is newer → sync is needed
- Sync re-runs cells in order to rebuild variables/imports

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                    VSCode UI                        │
│  ┌──────────────────────────────────────────────┐  │
│  │        Notebook Editor (.ipynb)              │  │
│  │                                              │  │
│  │  Cell 1: import pandas as pd      [▶️ Run]   │  │
│  │  Cell 2: df = pd.read_csv(...)    [▶️ Run]   │  │
│  │  Cell 3: df.head()                [▶️ Run]   │  │
│  └──────────────────────────────────────────────┘  │
│                       ↓                             │
│  ┌──────────────────────────────────────────────┐  │
│  │     MCP Notebook Controller                  │  │
│  │  - Handle cell execution events              │  │
│  │  - Stream outputs to UI                      │  │
│  │  - Manage execution queue                    │  │
│  └──────────────────────────────────────────────┘  │
│                       ↓                             │
│  ┌──────────────────────────────────────────────┐  │
│  │           MCP Client                         │  │
│  │  - Spawn Python MCP server (stdio)           │  │
│  │  - Send JSON-RPC requests                    │  │
│  │  - Parse JSON-RPC responses                  │  │
│  │  - Auto-restart on crash                     │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                       ↕ stdio (JSON-RPC)
┌─────────────────────────────────────────────────────┐
│              Python MCP Server                      │
│  ┌──────────────────────────────────────────────┐  │
│  │        Session Manager                       │  │
│  │  - Manage Jupyter kernel lifecycle           │  │
│  │  - Async execution queue                     │  │
│  │  - IOPub message listener                    │  │
│  │  - Handoff protocol (sync detection)         │  │
│  └──────────────────────────────────────────────┘  │
│                       ↕                             │
│  ┌──────────────────────────────────────────────┐  │
│  │       Jupyter Kernel (Python)                │  │
│  │  - ipykernel process                         │  │
│  │  - Execute Python code                       │  │
│  │  - Maintain variable state                   │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                       ↕
┌─────────────────────────────────────────────────────┐
│              AI Agent (e.g., Claude)                │
│  - Calls same MCP tools as extension                │
│  - Shares kernel state, execution queue, notebook   │
│  - Collaborative workflow with human                │
└─────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **NotebookController** | VSCode API integration, cell execution orchestration |
| **McpClient** | Stdio communication with Python server, request/response handling |
| **Python MCP Server** | Kernel management, execution queue, handoff protocol |
| **Jupyter Kernel** | Python code execution, variable state |

### Communication Flow

1. **User Action**: User presses `Shift+Enter` on cell
2. **VSCode Event**: `executeHandler()` called by VSCode
3. **MCP Request**: `mcpClient.runCellAsync()` sends JSON-RPC request via stdin
4. **Python Server**: Queues execution, returns task ID
5. **Polling Loop**: Extension polls `getExecutionStream()` every 500ms
6. **Incremental Updates**: New outputs appended to cell as they arrive
7. **Completion**: Loop exits when status = 'completed' or 'error'

## 🔧 Development

### Project Structure
```
vscode-extension/
├── src/
│   ├── extension.ts          # Entry point (activate/deactivate)
│   ├── mcpClient.ts           # MCP server communication
│   ├── notebookController.ts  # VSCode NotebookController
│   └── types.ts               # TypeScript interfaces
├── .vscode/
│   ├── launch.json            # Debug configurations
│   └── tasks.json             # Build tasks
├── package.json               # Extension manifest
├── tsconfig.json              # TypeScript config
└── README.md                  # This file
```

### Build
```bash
npm install        # Install dependencies
npm run compile    # Compile TypeScript
npm run watch      # Watch mode for development
```

### Test
```bash
# Launch Extension Development Host
# Press F5 in VSCode

# Or from terminal
code --extensionDevelopmentPath=.
```

### Debug
1. Open `vscode-extension/` folder in VSCode
2. Press `F5` to launch Extension Development Host
3. Set breakpoints in `.ts` files
4. Open a notebook and run cells
5. Debugger stops at breakpoints

### Logs
- **Extension Logs**: Debug Console in Extension Development Host
- **MCP Server Logs**: Command Palette → `MCP Jupyter: Show Server Logs`

## 🐛 Troubleshooting

### Server Won't Start
**Symptom**: Extension activates but cell execution fails

**Solutions**:
1. Check MCP server path:
   - Open Settings → `mcp-jupyter.serverPath`
   - Verify path exists: `ls /path/to/mcp-server-jupyter`
2. Check Python executable:
   - Settings → `mcp-jupyter.pythonPath`
   - Test: `python -m src.main` in server directory
3. View server logs:
   - Command Palette → `MCP Jupyter: Show Server Logs`
   - Look for error messages

### Outputs Not Appearing
**Symptom**: Cell executes but no output shown

**Solutions**:
1. Check polling interval:
   - Settings → `mcp-jupyter.pollingInterval`
   - Try increasing to 1000ms
2. Restart server:
   - Command Palette → `MCP Jupyter: Restart Server`
3. Check for errors in output channel

### Kernel Not Syncing After AI Edits
**Symptom**: Notebook edited externally but kernel state doesn't update

**Solutions**:
1. Close and reopen notebook (triggers sync detection)
2. Manually restart kernel:
   - Command Palette → `MCP Jupyter: Select Python Environment`
   - Re-select current environment (forces restart)
3. Check file timestamps:
   - Server logs show: "Sync needed: disk_time > kernel_time"

### Extension Crashes
**Symptom**: Extension stops responding

**Solutions**:
1. Check auto-restart setting:
   - Settings → `mcp-jupyter.autoRestart` = true
2. View crash logs in output channel
3. Manually restart:
   - Command Palette → `MCP Jupyter: Restart Server`

## 📝 Known Limitations

1. **Windows Event Loop Warning**: Harmless warning about ZMQ on Windows (can be ignored)
2. **Single Kernel Per Notebook**: Each notebook has one kernel (standard Jupyter behavior)
3. **No Interrupt Support**: Cell interruption not yet implemented (coming soon)
4. **Python Only**: Currently only Python kernels supported (other languages possible later)

## 🤝 Contributing

We welcome contributions! Here's how to get started:

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/my-feature`
3. **Make** changes with clear commits
4. **Test** thoroughly (run extension, execute cells, check outputs)
5. **Submit** PR with description

### Code Style
- TypeScript: Follow existing style (ESLint rules in `package.json`)
- Comments: Document public methods with JSDoc
- Error Handling: Always catch errors and log to output channel

## 📄 License

[Your License Here]

## 🙏 Credits

Built with:
- [VSCode Extension API](https://code.visualstudio.com/api)
- [MCP SDK](https://github.com/anthropics/mcp)
- [Jupyter Client](https://github.com/jupyter/jupyter_client)

## 🔗 Related Projects

- **MCP Server Jupyter**: The Python backend server ([link](../tools/mcp-server-jupyter/))
- **Model Context Protocol**: Official spec ([link](https://spec.modelcontextprotocol.io/))

## 📞 Support

For issues or questions:
1. Check this README and [VSCODE_EXTENSION_PLAN.md](../VSCODE_EXTENSION_PLAN.md)
2. View server logs (Command Palette → Show Server Logs)
3. Open an issue with:
   - VSCode version
   - Extension version
   - Python version
   - Full error message from logs
   - Steps to reproduce
