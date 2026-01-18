#!/bin/bash
set -e

# Publish script for PyPI
echo "🚀 Publishing mcp-server-jupyter to PyPI..."

# Navigate to package directory
cd "$(dirname "$0")/.."

# Check for PyPI token
if [ -z "$POETRY_PYPI_TOKEN_PYPI" ]; then
    echo "⚠️  Warning: POETRY_PYPI_TOKEN_PYPI not set"
    echo "   Set it with: export POETRY_PYPI_TOKEN_PYPI=<token>"
    echo "   Or configure: poetry config pypi-token.pypi <token>"
    echo ""
fi

# Confirm version
VERSION=$(grep '^version = ' pyproject.toml | cut -d'"' -f2)
echo "📌 Current version: $VERSION"
echo ""

# Check if package exists
if [ ! -d dist/ ] || [ -z "$(ls -A dist/)" ]; then
    echo "❌ No built packages found. Run ./scripts/build.sh first"
    exit 1
fi

# Ask for confirmation
read -p "🤔 Publish version $VERSION to PyPI? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Cancelled"
    exit 1
fi

# Publish to TestPyPI first (recommended)
echo ""
echo "1️⃣  Publishing to TestPyPI (test environment)..."
read -p "   Publish to TestPyPI first? (Y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    poetry publish -r testpypi
    echo ""
    echo "✅ Published to TestPyPI"
    echo "📝 Test installation with:"
    echo "   pip install --index-url https://test.pypi.org/simple/ mcp-server-jupyter"
    echo ""
    read -p "   Continue to production PyPI? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Cancelled production publish"
        exit 0
    fi
fi

# Publish to production PyPI
echo ""
echo "2️⃣  Publishing to PyPI (PRODUCTION)..."
poetry publish

echo ""
echo "✅ Published to PyPI!"
echo ""
echo "📝 Installation command:"
echo "   pip install mcp-server-jupyter"
echo ""
echo "🔗 Package URL:"
echo "   https://pypi.org/project/mcp-server-jupyter/"
