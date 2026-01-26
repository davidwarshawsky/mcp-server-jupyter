# 🚀 1-Minute Quick Start

Get your AI Data Science Assistant running in 60 seconds.

---

## ⚡ One-Click Setup

### Step 1: Install the Extension

Search for **`MCP Agent Kernel`** in VS Code Extensions and click **Install**.

Or install from command line:
```bash
code --install-extension mcp-jupyter.mcp-agent-kernel
```

### Step 2: Run the Wizard

Press `F1` (or `Ctrl+Shift+P` / `Cmd+Shift+P`) and type:

```
MCP Jupyter: Quick Start
```

### Step 3: Choose "Automatic Setup"

Select **"🚀 Automatic Setup"** (the first option).

*That's it.* The extension will automatically:

- ✅ Create a private Python environment
- ✅ Install the MCP Server  
- ✅ Connect the AI Agent
- ✅ Open a test notebook

**No terminal commands. No configuration. Just click.**

---

## 🧪 Verify It Works

1. The **Example Notebook** opens automatically after setup
2. Click the **▶️ Run** button on the first cell
3. If you see `Hello from MCP Jupyter!`, you're ready to code!

---

## 🎯 What's Next?

### Try Your First AI-Assisted Analysis

1. Open any `.ipynb` notebook
2. Select **MCP Agent Kernel** as the kernel
3. Write natural language in a markdown cell:
   ```markdown
   # Analysis Request
   Load the iris dataset and show me a correlation heatmap
   ```
4. The AI assistant will generate and execute the code for you

### Explore Key Features

| Feature | Command |
|---------|---------|
| Start AI Assistant | `MCP Jupyter: Start Server` |
| View Variables | `MCP Jupyter: Show Variable Dashboard` |
| Health Check | `MCP Jupyter: Health Check` |
| View Logs | `MCP Jupyter: Show Server Logs` |

---

## ❓ Troubleshooting

### "Python not found"

Install Python 3.9+ from [python.org](https://www.python.org/downloads/) or use your system package manager.

### "Connection failed"

1. Press `F1` → `MCP Jupyter: Show Server Logs`
2. Look for error messages
3. Try `MCP Jupyter: Restart Server`

### Still stuck?

- 📖 [Full Documentation](./getting-started/installation.md)
- 🐛 [Report an Issue](https://github.com/example/mcp-jupyter/issues)
- 💬 [Community Discord](https://discord.gg/mcp-jupyter)

---

## 📺 Video Walkthrough

*(Coming soon: Embedded video demo)*

To generate the walkthrough video locally:

```bash
# Install dependencies
npm install -g code-server playwright

# Start code-server
code-server --bind-addr 127.0.0.1:8080 --auth none .

# Record the demo
npx ts-node scripts/record_setup_walkthrough.ts
```

The video will be saved to `docs/assets/demos/setup_guide.webm`.
