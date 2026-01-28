# MCP Jupyter: The Superpowered VS Code Extension

<div align="center">

**Stop losing work to crashed kernels. Stop wrestling with pandas. Start using superpowers.**

</div>

---

## 👋 What is MCP Jupyter?

MCP Jupyter is a free, open-source VS Code extension that gives you **superpowers** for your Jupyter notebooks. It is designed to provide a more resilient, powerful, and user-friendly data science experience within VS Code.

This project is composed of two main parts:
1.  A **VS Code Extension** (`vscode-extension`) that provides the user interface and frontend logic.
2.  A **Jupyter Server Backend** (`tools/mcp-server-jupyter`) that manages kernels, state, and executes the "superpowers".

## Our Philosophy: Do No Harm

This tool is designed to be a lightweight, reliable companion that respects your development environment. Our core principles are:

-   **Works Out of the Box:** The base installation is minimal and has no heavy dependencies. It's designed to "just work."
-   **Do No Harm:** We never automatically install heavy libraries or modify your environment. Advanced features requiring packages like `pandas` or `duckdb` are strictly opt-in.
-   **Act as a Tool, Not a Server:** The extension runs as a simple tool under your control. It avoids complex background processes, ensuring it stays lightweight and predictable.

| Before MCP Jupyter                               | After MCP Jupyter                                |
| ------------------------------------------------ | ------------------------------------------------ |
| 😭 Kernel crashes and lost work                  | 😎 **Automatic crash recovery**                     |
| 🐌 Browser freezes with large outputs            | ⚡️ **No-freeze large outputs**                    |
| 🤯 Complex pandas code for simple queries        | 🔮 **SQL queries on your DataFrames**            |
|  tedious boilerplate for EDA                    | 🤖 **60-second automated EDA**                   |

---

## 🚀 Getting Started (for Developers)

As this project is under active development, it is not yet published on the VS Code Marketplace. To use it, you will need to build it from source.

### Prerequisites

*   [Node.js and npm](https://nodejs.org/en/download/)
*   [Python 3.8+](https://www.python.org/downloads/)
*   [Visual Studio Code](https://code.visualstudio.com/)

### 1. Build the Backend

The `mcp-server-jupyter` is a Python package.

```bash
# Navigate to the server directory
cd tools/mcp-server-jupyter

# Install dependencies (using poetry or pip from pyproject.toml)
pip install poetry
poetry install

# Build the wheel
poetry build
```

### 2. Build and Install the Frontend

The VS Code extension bundles the backend server.

```bash
# Navigate to the extension directory
cd ../../vscode-extension

# Install npm dependencies
npm install

# The `prepublish` script should automatically copy the backend wheel.
# If not, you may need to run scripts manually.
# Now, package the extension into a .vsix file
npm install -g @vscode/vsce
vsce package

# In VS Code, open the Extensions view (Ctrl+Shift+X)
# Click the "..." menu in the top-right corner and select "Install from VSIX..."
# Choose the .vsix file you just created.
```

### 3. Using the Extension

1.  After installing, reload VS Code.
2.  Open a Jupyter Notebook (`.ipynb` file).
3.  Click the kernel selector in the top-right corner.
4.  Choose "**MCP Agent Kernel**".
5.  You can now try the superpowers!

---

## ✨ Superpowers

### 🔮 SQL on DataFrames: The 10x Easier Way to Query

Stop writing verbose pandas code. Start writing clean, readable SQL.

**Why it's a superpower:**

*   **Zero-copy:** In-memory SQL on your DataFrames. No data duplication.
*   **Readable:** 10x more readable than complex pandas code.
*   **Familiar:** If you know SQL, you know how to use it.

### 🤖 Auto-EDA: Exploratory Data Analysis in 60 Seconds

Stop writing matplotlib and seaborn boilerplate. Start getting instant insights. In a cell, type:

```python
/prompt auto-analyst
```

**What it does:**

*   **Data Health Check:** Finds missing values and outliers.
*   **Visualizations:** Generates 3+ plots (distributions, correlations, etc.).
*   **Summary & Recommendations:** Tells you what to look for next.

### 🛡️ The Reaper: Your Guardian Against Crashed Kernels

Stop losing your work when a kernel crashes. The Reaper automatically brings it back to life.

**How it works:**

*   **Monitors:** Keeps an eye on your kernel.
*   **Revives:** Restarts it in <2 seconds if it crashes.
*   **Recovers:** Restores your notebook's state.

---

## 🤝 Contributing

We welcome contributions! Please see our [**Contributing Guide**](CONTRIBUTING.md) to get started.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
