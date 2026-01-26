#!/bin/bash
set -e # Exit immediately if a command exits with a non-zero status.

echo "Building Python server wheel..."
# Navigate to the canonical server directory relative to this script
cd "$(dirname "$0")/../../tools/mcp-server-jupyter"

# Ensure poetry is available
if ! command -v poetry &> /dev/null
then
    echo "poetry could not be found, please install it."
    exit 1
fi

# Remove old dists and build the wheel
rm -rf dist
poetry build

echo "Copying wheel to VS Code extension..."
# Navigate back to the extension directory's root
cd ../../vscode-extension

# Create destination directory and copy the new wheel
DEST_DIR="python_dist"
mkdir -p "$DEST_DIR"
rm -f "$DEST_DIR"/*.whl # Clean out any old wheels
cp ../tools/mcp-server-jupyter/dist/*.whl "$DEST_DIR"/

echo "Python server wheel successfully packaged for the extension."
