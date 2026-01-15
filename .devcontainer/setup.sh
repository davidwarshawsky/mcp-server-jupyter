#!/bin/bash
# .devcontainer/setup.sh - Automated Codespaces setup

set -e

echo "🚀 Setting up MCP Jupyter Server development environment..."

# 1. Install Python dependencies
echo "📦 Installing Python server..."
cd tools/mcp-server-jupyter
pip install -e ".[superpowers]"
cd ../..

# 2. Install VS Code extension dependencies
echo "📦 Installing VS Code extension dependencies..."
cd vscode-extension
npm install
npm run bundle-python
npm run compile
cd ..

# 3. Install documentation tools
echo "📚 Installing documentation tools..."
pip install mkdocs-material mkdocstrings[python] mkdocs-git-revision-date-localized-plugin

# 4. Run tests to verify setup
echo "🧪 Running verification tests..."
cd tools/mcp-server-jupyter
pytest tests/test_superpowers.py tests/test_prompts.py -v
cd ../..

# 5. Start documentation server in background
echo "📖 Starting documentation server..."
mkdocs serve --dev-addr=0.0.0.0:8000 &

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Open a Jupyter notebook in VS Code"
echo "  2. Select 'MCP Agent Kernel' as the kernel"
echo "  3. Try a Superpower:"
echo "     /prompt auto-analyst"
echo ""
echo "  Docs available at: http://localhost:8000"
echo "  Server will start automatically when needed"
echo ""
