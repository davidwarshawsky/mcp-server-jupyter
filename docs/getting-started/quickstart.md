# Quick Start Guide

Get your AI Research Assistant running in under 2 minutes.

## Zero-Friction Setup

MCP Jupyter uses **invisible setup** - there's no wizard to click through. Just install and go.

### Step 1: Install the Extension

1. Open VS Code
2. Go to Extensions (`Ctrl+Shift+X` / `Cmd+Shift+X`)
3. Search for "MCP Agent Kernel"
4. Click **Install**

That's it! The extension handles everything else automatically.

### Step 2: Open a Notebook

1. Open any `.ipynb` file, or create a new one:
   - `Ctrl+Shift+P` → "Create: New Jupyter Notebook"

2. Select the **MCP Agent Kernel** from the kernel picker in the top-right

![Kernel Selection](../assets/kernel-select.png)

### Step 3: Start Working

The kernel is ready. Your AI assistant can now:

- Execute code in cells
- Inspect variables without loading entire DataFrames
- Run SQL queries on your data
- Generate plots with automatic inline rendering

## What Happens Behind the Scenes

When you first activate the extension:

1. **Environment Detection**: Finds your Python installation
2. **Silent Install**: Creates a managed virtual environment with dependencies
3. **Server Start**: Launches the MCP server on a random port
4. **Ready**: Shows a discrete toast notification when ready

You don't see any of this - it just works.

## First Commands

Try these in your notebook:

```python
# Cell 1: Create some data
import pandas as pd

sales = pd.DataFrame({
    "region": ["North", "South", "East", "West"],
    "revenue": [10000, 15000, 12000, 18000]
})
sales
```

```python
# Cell 2: Use SQL Magic! (Yes, native SQL in a Python cell)
%%duckdb
SELECT region, revenue
FROM sales
WHERE revenue > 12000
ORDER BY revenue DESC
```

```python
# Cell 3: Create a plot (automatically rendered inline)
import matplotlib.pyplot as plt

plt.bar(sales['region'], sales['revenue'])
plt.title("Revenue by Region")
plt.show()
```

## Troubleshooting

### Extension Not Working?

1. **Check Status Bar**: Look for "MCP Jupyter" in the bottom status bar
2. **Show Logs**: `Ctrl+Shift+P` → "MCP Jupyter: Show Server Logs"
3. **Restart Server**: `Ctrl+Shift+P` → "MCP Jupyter: Restart Server"

### Behind a Corporate Proxy?

The extension automatically inherits proxy settings from:

- Environment variables (`HTTP_PROXY`, `HTTPS_PROXY`)
- VS Code's `http.proxy` setting

If you're still having issues, check your `SSL_CERT_FILE` or `PIP_CERT` environment variables.

### Emergency Stop

If a cell gets stuck in an infinite loop:

1. Click "MCP Jupyter" in status bar → "Emergency Stop"
2. Or: `Ctrl+Shift+P` → "MCP Jupyter: Emergency Stop (Kill Kernel)"

- **Click once**: Sends interrupt (like `Ctrl+C`)
- **Click twice within 5s**: Force kills the kernel and restarts

## Next Steps

- [SQL Magic Guide](../superpowers/sql-magic.md) - Write native SQL on DataFrames
- [Asset Rendering](../superpowers/asset-rendering.md) - How plots are displayed inline
- [All Superpowers](../superpowers/index.md) - Full list of AI-powered features
