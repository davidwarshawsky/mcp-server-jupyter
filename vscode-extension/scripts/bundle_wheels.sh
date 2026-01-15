#!/bin/bash
# Bundle Python Dependencies for Offline Installation (Fat VSIX)
# This script downloads platform-specific wheel files to support:
# - Firewalled corporate networks
# - Air-gapped machines
# - Reliable offline installation

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTENSION_DIR="$(dirname "$SCRIPT_DIR")"
WHEELS_DIR="$EXTENSION_DIR/python_server/wheels"
SERVER_DIR="$EXTENSION_DIR/python_server"

echo "=========================================="
echo "Bundling Python Dependencies (Fat VSIX)"
echo "=========================================="

# Check if python_server exists
if [ ! -d "$SERVER_DIR" ]; then
    echo "❌ Error: python_server directory not found at $SERVER_DIR"
    echo "Run 'npm run bundle-python' first to copy the server source."
    exit 1
fi

# Create wheels directory
mkdir -p "$WHEELS_DIR"

# Clean existing wheels
echo "🧹 Cleaning existing wheels..."
rm -rf "$WHEELS_DIR"/*

echo "📦 Downloading dependencies for multiple platforms..."
echo ""

# Python versions to support (VS Code typically uses Python 3.9+)
PYTHON_VERSIONS=("3.9" "3.10" "3.11" "3.12")

# Platforms to support
# manylinux2014_x86_64: Linux (Intel/AMD)
# manylinux2014_aarch64: Linux (ARM, e.g., Raspberry Pi)
# win_amd64: Windows (64-bit)
# macosx_11_0_arm64: macOS (Apple Silicon)
# macosx_11_0_x86_64: macOS (Intel)
PLATFORMS=(
    "manylinux2014_x86_64"
    "manylinux2014_aarch64"
    "win_amd64"
    "macosx_11_0_arm64"
    "macosx_11_0_x86_64"
)

# Use the highest Python version for the download (most compatible)
PRIMARY_PY_VERSION="3.11"

echo "Primary Python Version: $PRIMARY_PY_VERSION"
echo "Target Platforms:"
for platform in "${PLATFORMS[@]}"; do
    echo "  - $platform"
done
echo ""

# Download dependencies
# Strategy: Download all dependencies first (which gets pure Python packages),
# then add platform-specific wheels for packages that need them
echo "⬇️  Downloading all dependencies (Step 1/2)..."
pip download \
    --dest "$WHEELS_DIR" \
    "$SERVER_DIR" 2>&1 | grep -v "Requirement already satisfied" || true

echo ""
echo "⬇️  Adding platform-specific wheels (Step 2/2)..."
# Now add platform-specific wheels (--only-binary) for compiled packages
for platform in "${PLATFORMS[@]}"; do
    echo "  → $platform"
    pip download \
        --dest "$WHEELS_DIR" \
        --only-binary=:all: \
        --python-version "$PRIMARY_PY_VERSION" \
        --platform "$platform" \
        --no-deps \
        "$SERVER_DIR" 2>&1 | grep -v "Requirement already satisfied" || true
done

echo ""
echo "🔍 Verifying downloaded wheels..."
WHEEL_COUNT=$(find "$WHEELS_DIR" -name "*.whl" | wc -l)
TAR_COUNT=$(find "$WHEELS_DIR" -name "*.tar.gz" | wc -l)

echo "  Found $WHEEL_COUNT wheel files (.whl)"
echo "  Found $TAR_COUNT source distributions (.tar.gz)"

if [ "$TAR_COUNT" -gt 0 ]; then
    echo ""
    echo "⚠️  Warning: Found source distributions. These may require compilation."
    echo "  For maximum compatibility, consider removing them:"
    find "$WHEELS_DIR" -name "*.tar.gz" -exec basename {} \;
fi

echo ""
echo "📊 Wheel bundle size:"
du -sh "$WHEELS_DIR"

echo ""
echo "✅ Wheel bundling complete!"
echo "  Location: $WHEELS_DIR"
echo "  Files: $WHEEL_COUNT wheels"
echo ""
echo "The extension will now support offline installation in:"
echo "  ✓ Corporate firewalled networks"
echo "  ✓ Air-gapped machines"
echo "  ✓ Environments without PyPI access"
