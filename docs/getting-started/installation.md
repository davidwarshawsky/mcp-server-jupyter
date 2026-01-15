# Installation

## Prerequisites

- **Python**: 3.10 or higher
- **Node.js**: 18 or higher (for VS Code extension development)
- **VS Code**: Latest version (for extension usage)

## Python Server Installation

### Option 1: With Superpowers (Recommended)

Install with all Superpower features (DuckDB SQL, Auto-EDA dependencies):

```bash
pip install "mcp-server-jupyter[superpowers]"
```

This includes:

- `duckdb>=1.1.0` - SQL queries on DataFrames
- Auto-installation of `pandas`, `numpy`, `matplotlib`, `seaborn` at runtime

### Option 2: Base Installation

Install base server without optional features:

```bash
pip install mcp-server-jupyter
```

!!! warning "Limited Features"
    Without superpowers, you won't have:
    
    - `query_dataframes` tool (DuckDB SQL)
    - `auto_analyst` prompt (requires matplotlib/seaborn)
    - Time Travel may have reduced functionality

### Option 3: Development Installation

For contributors or advanced users:

```bash
git clone https://github.com/yourusername/mcp-jupyter-server.git
cd mcp-jupyter-server/tools/mcp-server-jupyter
pip install -e ".[superpowers]"
```

The `-e` flag installs in editable mode, so changes to the code take effect immediately.

## VS Code Extension Installation

### From VS Code Marketplace

1. Open VS Code
2. Go to Extensions (`Ctrl+Shift+X` or `Cmd+Shift+X`)
3. Search for "MCP Agent Kernel"
4. Click **Install**

### From VSIX File (Pre-release)

If testing a pre-release version:

```bash
code --install-extension mcp-agent-kernel-0.1.0.vsix
```

### Extension Setup

After installing the extension:

1. **First-time Setup Wizard** will guide you through:
   - Python environment selection
   - Server installation verification
   - Test cell execution

2. **Manual Configuration** (if needed):
   
   Open VS Code Settings (`Ctrl+,`) and configure:
   
   ```json
   {
     "mcp-agent-kernel.pythonPath": "/path/to/python",
     "mcp-agent-kernel.serverPort": 3000,
     "mcp-agent-kernel.enableSuperp
owers": true
   }
   ```

## Verification

### Test Python Server

```bash
# Start server manually
python -m src.main --transport websocket --port 3000

# You should see:
# INFO: Server started on ws://127.0.0.1:3000
# INFO: SessionManager initialized
```

### Test Extension Integration

1. Create a new Jupyter notebook in VS Code
2. Select "MCP Agent Kernel" as the kernel
3. Execute a test cell:

   ```python
   print("Hello from MCP Jupyter Server!")
   ```

4. Verify output appears without errors

### Test Superpowers

```python
# Test DuckDB SQL
import pandas as pd
df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})

# This should work if superpowers installed:
query_dataframes("SELECT a, b FROM df WHERE a > 1")
```

## Troubleshooting

### "Command 'query_dataframes' not found"

**Cause**: DuckDB not installed

**Solution**:
```bash
pip install "mcp-server-jupyter[superpowers]"
# or manually:
pip install duckdb
```

### "Kernel crashed on startup"

**Cause**: Python environment mismatch

**Solution**:

1. Check Python version: `python --version` (must be 3.10+)
2. Reinstall in correct environment:
   ```bash
   python -m pip install --force-reinstall mcp-server-jupyter
   ```

### "Extension not connecting to server"

**Cause**: Port already in use

**Solution**:

1. Find process using port 3000:
   ```bash
   lsof -i :3000  # macOS/Linux
   netstat -ano | findstr :3000  # Windows
   ```
2. Kill the process or change port in settings

### "ModuleNotFoundError: No module named 'mcp'"

**Cause**: Server not installed in active Python environment

**Solution**:

1. Verify which Python VS Code is using:
   - Open Command Palette (`Ctrl+Shift+P`)
   - Select "Python: Select Interpreter"
2. Install in that environment:
   ```bash
   /path/to/that/python -m pip install mcp-server-jupyter
   ```

## Next Steps

- [Quick Start Guide](quickstart.md) - Execute your first cells
- [VS Code Extension Usage](vscode.md) - Features and shortcuts
- [Superpowers Overview](../superpowers/index.md) - Unlock advanced features
