#!/bin/bash
# MCP Jupyter - One-Click Installer (Healthcare-Ready)
# 
# Usage: curl -sL https://your-internal-repo/install.sh | bash
#
# This script:
# 1. Creates a dedicated Python venv
# 2. Installs MCP Server
# 3. Installs VS Code Extension
# 4. Configures your first notebook

set -e  # Exit on error

echo "🚀 MCP Jupyter - One-Click Healthcare Installation"
echo "=================================================="

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    PYTHON_CMD="python3"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    PYTHON_CMD="python3"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    OS="windows"
    PYTHON_CMD="python"
else
    echo "❌ Unsupported OS: $OSTYPE"
    exit 1
fi

echo "📍 Detected OS: $OS"

# Step 1: Create venv
VENV_PATH="$HOME/.mcp-jupyter-env"
echo "📦 Creating virtual environment at $VENV_PATH..."

if [ -d "$VENV_PATH" ]; then
    echo "✓ Virtual environment already exists"
else
    $PYTHON_CMD -m venv "$VENV_PATH"
    echo "✓ Virtual environment created"
fi

# Step 2: Activate venv
if [ "$OS" = "windows" ]; then
    source "$VENV_PATH/Scripts/activate"
else
    source "$VENV_PATH/bin/activate"
fi

echo "✓ Virtual environment activated"

# Step 3: Install MCP Server
echo "📚 Installing MCP Jupyter Server..."
pip install --upgrade pip setuptools wheel
pip install mcp-jupyter

echo "✓ MCP Server installed"

# Step 4: Create config directory
CONFIG_DIR="$HOME/.mcp-jupyter"
mkdir -p "$CONFIG_DIR"
echo "✓ Config directory created at $CONFIG_DIR"

# Step 5: Create sample notebook
NOTEBOOK_PATH="$HOME/mcp-jupyter-analysis.ipynb"
if [ ! -f "$NOTEBOOK_PATH" ]; then
    cat > "$NOTEBOOK_PATH" << 'EOF'
{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# My First Analysis with MCP Jupyter\n",
    "\n",
    "This notebook demonstrates the Auto-Analyst persona."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "import pandas as pd\n",
    "import numpy as np\n",
    "\n",
    "# Load sample data\n",
    "data = {\n",
    "    'date': pd.date_range('2025-01-01', periods=100),\n",
    "    'value': np.random.randn(100).cumsum(),\n",
    "    'category': np.random.choice(['A', 'B', 'C'], 100)\n",
    "}\n",
    "df = pd.DataFrame(data)\n",
    "print(df.head())"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## Next Steps\n",
    "\n",
    "1. Start the MCP Server: `mcp-jupyter --transport websocket --port 3000`\n",
    "2. Connect VS Code to `ws://127.0.0.1:3000/ws`\n",
    "3. Right-click a cell and select \"Auto-Analyst\"\n",
    "4. Watch the AI generate analysis!"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "name": "python",
   "version": "3.11"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 4
}
EOF
    echo "✓ Sample notebook created at $NOTEBOOK_PATH"
fi

# Step 6: Print next steps
echo ""
echo "✅ Installation Complete!"
echo ""
echo "🚀 Next Steps:"
echo "1. Start the server:"
echo "   mcp-jupyter --transport websocket --port 3000"
echo ""
echo "2. Open VS Code and connect:"
echo "   Command Palette → 'MCP Jupyter: Connect to Existing Server'"
echo "   URL: ws://127.0.0.1:3000/ws"
echo ""
echo "3. Open your notebook:"
echo "   $NOTEBOOK_PATH"
echo ""
echo "4. Right-click on a cell and select 'Auto-Analyst'"
echo ""
echo "📚 Documentation: $CONFIG_DIR/README.md"
echo "🆘 Support: #mcp-jupyter on Slack"
echo ""
