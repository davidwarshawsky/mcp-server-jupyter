# Asset Rendering: Inline Plots and Images

See your visualizations directly in the notebook - no file browser needed.

## The Problem

When AI agents create plots, they often save to disk:

```
[IMAGE SAVED TO: assets/plot_abc123.png]
```

This forces users to:

1. Open the file explorer
2. Navigate to the assets folder
3. Double-click the file
4. Check if it looks right
5. Go back to the notebook

## The Solution: Automatic Inline Rendering

MCP Jupyter includes a **custom notebook renderer** that automatically displays images inline:

```python
import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 10, 100)
plt.plot(x, np.sin(x))
plt.title("Sine Wave")
plt.show()
```

**Result:** The plot appears directly in the cell output, not as a file path.

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Python Kernel (matplotlib/plotly/etc.)                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Output: { "image/png": "base64..." }                   │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  MCP Server (sanitize_outputs)                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  1. Save to assets/plot_abc123.png (for git-safety)     │   │
│  │  2. Output: { "application/vnd.mcp.asset+json": {       │   │
│  │       "type": "image/png",                              │   │
│  │       "content": "base64...",                           │   │
│  │       "path": "assets/plot_abc123.png"                  │   │
│  │     }}                                                  │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  VS Code Notebook Renderer (renderer.js)                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Renders <img src="data:image/png;base64,...">          │   │
│  │  Shows in cell output automatically                     │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Benefits

1. **Human sees**: The actual image, inline
2. **AI agent sees**: `[PNG ASSET RENDERED INLINE]` (token-efficient)
3. **Git sees**: `assets/` folder is auto-gitignored (clean history)

## Supported Formats

| Format | Extension | Rendered |
|--------|-----------|----------|
| PNG    | .png      | ✅ Yes   |
| JPEG   | .jpg      | ✅ Yes   |
| SVG    | .svg      | ✅ Yes   |
| GIF    | .gif      | ✅ Yes   |

## Git-Safe Asset Management

All images are saved to an `assets/` folder which is:

1. **Auto-gitignored**: We add `assets/` to `.gitignore` automatically
2. **Garbage collected**: Unused assets are pruned when you clear outputs

This prevents your git history from being polluted with binary files.

### Manual Cleanup

To remove unused assets:

```python
# From your notebook
await mcp.call_tool("prune_unused_assets", {
    "notebook_path": "analysis.ipynb",
    "dry_run": True  # Set to False to actually delete
})
```

Or via command palette:

`Ctrl+Shift+P` → "MCP Jupyter: Prune Unused Assets"

## Large Output Handling

For outputs that would blow up the AI's context window:

### Text Offloading

Long text outputs (>10,000 characters) are automatically saved to disk:

```
[CONTENT SAVED TO: assets/text_abc123.txt]
Preview (first 500 chars):
...
```

The AI gets the preview, but the full content is preserved.

### DataFrame Display

DataFrames with >50 columns show a smart summary instead of all columns:

```
### Type: DataFrame
- Shape: (10000, 5000)
- Columns: (5000 total - too many to list)
  First 10: ['col1', 'col2', ...]
  Last 10: ['col4991', 'col4992', ...]
  By dtype: {'float64': 4000, 'object': 500, 'int64': 500}
  💡 Use search_dataframe_columns(df_name, 'pattern') to find specific columns
```

## Troubleshooting

### Plot Not Appearing?

1. Make sure you're using the **MCP Agent Kernel**
2. Check that `matplotlib.pyplot.show()` is called
3. Try running the cell again

### Image Shows as Text?

The renderer might not be loaded. Try:

1. Close and reopen the notebook
2. Or: `Ctrl+Shift+P` → "Developer: Reload Window"

### Asset Folder Growing Large?

Run the garbage collector:

```
Ctrl+Shift+P → "MCP Jupyter: Prune Unused Assets"
```

## See Also

- [Quick Start](../getting-started/quickstart.md) - Get up and running
- [SQL Magic](./sql-magic.md) - Write SQL on DataFrames
- [All Superpowers](./index.md) - Full feature list
