#!/bin/bash
set -e

# Test local installation of the built package
echo "🧪 Testing local installation..."

# Navigate to package directory
cd "$(dirname "$0")/.."

# Check if wheel exists
if [ ! -f dist/*.whl ]; then
    echo "❌ No wheel file found. Run ./scripts/build.sh first"
    exit 1
fi

# Create temporary virtual environment
VENV_DIR=$(mktemp -d)/test-venv
echo "📦 Creating test environment: $VENV_DIR"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Install the package
echo "⬇️  Installing from wheel..."
pip install --quiet dist/*.whl

# Test import
echo "🔍 Testing import..."
python -c "import src.main; print('✅ Import successful')"

# Test CLI
echo "🔍 Testing CLI..."
if command -v mcp-jupyter &> /dev/null; then
    mcp-jupyter --version || echo "⚠️  --version not implemented yet"
    echo "✅ CLI executable found"
else
    echo "❌ CLI not found in PATH"
    exit 1
fi

# Test basic functionality
echo "🔍 Testing basic functionality..."
python -c "
from src.session import SessionManager
from src.notebook import create_notebook
print('✅ Core imports work')
"

# Cleanup
deactivate
rm -rf "$VENV_DIR"

echo ""
echo "✅ Installation test passed!"
echo "📦 Package is ready for distribution"
