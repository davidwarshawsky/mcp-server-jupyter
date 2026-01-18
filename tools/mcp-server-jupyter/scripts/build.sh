#!/bin/bash
set -e

# Build script for PyPI distribution
echo "🔨 Building mcp-server-jupyter for PyPI..."

# Navigate to package directory
cd "$(dirname "$0")/.."

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf dist/ build/ *.egg-info

# Check if poetry is installed
if ! command -v poetry &> /dev/null; then
    echo "❌ Poetry not found. Install with: pip install poetry"
    exit 1
fi

# Validate pyproject.toml
echo "✅ Validating pyproject.toml..."
poetry check

# Build the package
echo "📦 Building distribution packages..."
poetry build

# List built packages
echo "✅ Build complete! Packages:"
ls -lh dist/

# Verify package contents
echo ""
echo "📋 Package contents:"
tar -tzf dist/*.tar.gz | head -20

echo ""
echo "✅ Build successful!"
echo ""
echo "📝 Next steps:"
echo "  1. Test installation: pip install dist/*.whl"
echo "  2. Test import: python -c 'import src.main'"
echo "  3. Test CLI: mcp-jupyter --help"
echo "  4. Publish to TestPyPI: poetry publish -r testpypi"
echo "  5. Publish to PyPI: poetry publish"
