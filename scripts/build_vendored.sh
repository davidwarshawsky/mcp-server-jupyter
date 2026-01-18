#!/usr/bin/env bash
# [FINAL PUNCH LIST #3] Build system with vendor directory for air-gapped installation
# 
# This script downloads all dependencies into a vendor/ directory
# and creates a distributable package with hash verification.
#
# Usage:
#   ./scripts/build_vendored.sh
#
# Output:
#   dist/mcp-jupyter-server-{version}-vendored.tar.gz

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="${1:-0.2.1}"

echo "🔨 Building MCP Jupyter Server v${VERSION} with vendored dependencies..."

# Clean previous builds
rm -rf "$PROJECT_ROOT/build" "$PROJECT_ROOT/dist" "$PROJECT_ROOT/vendor"
mkdir -p "$PROJECT_ROOT/vendor" "$PROJECT_ROOT/dist"

# Read dependencies from pyproject.toml or requirements.txt
if [ -f "$PROJECT_ROOT/pyproject.toml" ]; then
    echo "📦 Extracting dependencies from pyproject.toml..."
    # Use poetry to export requirements
    cd "$PROJECT_ROOT"
    if command -v poetry &> /dev/null; then
        poetry export -f requirements.txt --output requirements.tmp.txt --without-hashes
    else
        echo "❌ Poetry not found. Please install poetry or provide requirements.txt"
        exit 1
    fi
    REQUIREMENTS_FILE="requirements.tmp.txt"
elif [ -f "$PROJECT_ROOT/requirements.txt" ]; then
    REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"
else
    echo "❌ No pyproject.toml or requirements.txt found"
    exit 1
fi

# Download wheels for all dependencies
echo "⬇️  Downloading wheels to vendor/ directory..."
python3 -m pip download \
    --dest "$PROJECT_ROOT/vendor" \
    --require-hashes \
    --only-binary :all: \
    -r "$REQUIREMENTS_FILE" || {
        echo "⚠️  Some packages don't support --require-hashes, downloading without hashes..."
        python3 -m pip download \
            --dest "$PROJECT_ROOT/vendor" \
            --only-binary :all: \
            -r "$REQUIREMENTS_FILE"
    }

# Generate hash manifest
echo "🔐 Generating hash manifest..."
cd "$PROJECT_ROOT/vendor"
sha256sum * > SHA256SUMS
cd "$PROJECT_ROOT"

# Create installation script
cat > "$PROJECT_ROOT/vendor/install.sh" << 'EOF'
#!/usr/bin/env bash
# Vendored installation script
# Verifies hashes before installation

set -euo pipefail

VENDOR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🔐 Verifying package integrity..."
cd "$VENDOR_DIR"
sha256sum -c SHA256SUMS || {
    echo "❌ Hash verification failed! Packages may be corrupted or tampered with."
    exit 1
}

echo "✅ All packages verified. Installing..."
python3 -m pip install --no-index --find-links="$VENDOR_DIR" *.whl

echo "✅ Installation complete!"
EOF

chmod +x "$PROJECT_ROOT/vendor/install.sh"

# Copy source code
echo "📁 Copying source code..."
mkdir -p "$PROJECT_ROOT/build/mcp-jupyter-server"
cp -r "$PROJECT_ROOT/tools/mcp-server-jupyter/src" "$PROJECT_ROOT/build/mcp-jupyter-server/"
cp -r "$PROJECT_ROOT/vendor" "$PROJECT_ROOT/build/mcp-jupyter-server/"
cp "$PROJECT_ROOT/LICENSE" "$PROJECT_ROOT/build/mcp-jupyter-server/"
cp "$PROJECT_ROOT/README.md" "$PROJECT_ROOT/build/mcp-jupyter-server/"
cp "$PROJECT_ROOT/ENVIRONMENT_VARIABLES.md" "$PROJECT_ROOT/build/mcp-jupyter-server/"

# Create launcher script
cat > "$PROJECT_ROOT/build/mcp-jupyter-server/launch.sh" << 'EOF'
#!/usr/bin/env bash
# MCP Jupyter Server Launcher

set -euo pipefail

SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if dependencies are installed
if ! python3 -c "import fastmcp" 2>/dev/null; then
    echo "📦 Dependencies not installed. Running installation..."
    "$SERVER_DIR/vendor/install.sh"
fi

# Launch server
cd "$SERVER_DIR"
exec python3 -m src.main "$@"
EOF

chmod +x "$PROJECT_ROOT/build/mcp-jupyter-server/launch.sh"

# Create tarball
echo "📦 Creating distributable package..."
cd "$PROJECT_ROOT/build"
tar -czf "$PROJECT_ROOT/dist/mcp-jupyter-server-${VERSION}-vendored.tar.gz" mcp-jupyter-server/
cd "$PROJECT_ROOT"

# Generate installation instructions
cat > "$PROJECT_ROOT/dist/INSTALL.txt" << EOF
MCP Jupyter Server v${VERSION} - Vendored Installation

This package contains all dependencies and can be installed on air-gapped systems.

Installation:
1. Extract the tarball:
   tar -xzf mcp-jupyter-server-${VERSION}-vendored.tar.gz

2. Run the installer:
   cd mcp-jupyter-server
   ./vendor/install.sh

3. Launch the server:
   ./launch.sh --websocket --port 3000

Notes:
- All dependencies are included and hash-verified
- No internet connection required for installation
- See ENVIRONMENT_VARIABLES.md for configuration options

For more information, visit:
https://github.com/your-org/mcp-server-jupyter
EOF

# Clean up temporary files
rm -f "$PROJECT_ROOT/requirements.tmp.txt"
rm -rf "$PROJECT_ROOT/build"

# Generate checksum for the tarball
cd "$PROJECT_ROOT/dist"
sha256sum "mcp-jupyter-server-${VERSION}-vendored.tar.gz" > "mcp-jupyter-server-${VERSION}-vendored.tar.gz.sha256"

echo ""
echo "✅ Build complete!"
echo ""
echo "📦 Package: dist/mcp-jupyter-server-${VERSION}-vendored.tar.gz"
echo "🔐 Checksum: dist/mcp-jupyter-server-${VERSION}-vendored.tar.gz.sha256"
echo "📄 Instructions: dist/INSTALL.txt"
echo ""
echo "📊 Package contents:"
du -sh "$PROJECT_ROOT/dist/mcp-jupyter-server-${VERSION}-vendored.tar.gz"
echo ""
echo "To test installation:"
echo "  cd /tmp"
echo "  tar -xzf $PROJECT_ROOT/dist/mcp-jupyter-server-${VERSION}-vendored.tar.gz"
echo "  cd mcp-jupyter-server"
echo "  ./launch.sh --help"
echo ""
