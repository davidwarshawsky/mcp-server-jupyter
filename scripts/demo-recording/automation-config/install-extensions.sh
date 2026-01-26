#!/bin/bash
# Install required extensions for demo recording

echo "Installing VS Code extensions..."

# Install Jupyter extension
/app/code-server/bin/code-server --install-extension ms-toolsai.jupyter --force

# Install Python extension
/app/code-server/bin/code-server --install-extension ms-python.python --force

echo "Extensions installed successfully"
