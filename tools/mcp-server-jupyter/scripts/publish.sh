#!/bin/bash
set -e

# [IIRB REMEDIATION] Automated publish script for CI/CD pipelines
# This script is meant to be called by CI/CD (GitHub Actions, GitLab CI, etc.)
# It removes all interactive prompts to ensure deterministic, repeatable releases.
# 
# Usage in CI/CD:
#   - Ensure POETRY_PYPI_TOKEN_PYPI environment variable is set
#   - Call: ./scripts/publish.sh [--test-only]
#
# Flags:
#   --test-only: Publish only to TestPyPI (for validation before production)

# Navigate to package directory
cd "$(dirname "$0")/.."

TEST_ONLY=false
if [[ "$1" == "--test-only" ]]; then
    TEST_ONLY=true
fi

# Verify PyPI token is set
if [ -z "$POETRY_PYPI_TOKEN_PYPI" ]; then
    echo "❌ ERROR: POETRY_PYPI_TOKEN_PYPI environment variable not set"
    echo "   Set it in CI/CD secrets or via: export POETRY_PYPI_TOKEN_PYPI=<token>"
    exit 1
fi

# Extract version from pyproject.toml
VERSION=$(grep '^version = ' pyproject.toml | cut -d'"' -f2)
echo "📌 Publishing version: $VERSION"

# Verify built packages exist
if [ ! -d dist/ ] || [ -z "$(ls -A dist/)" ]; then
    echo "❌ ERROR: No built packages found in dist/"
    echo "   Run: ./scripts/build.sh first"
    exit 1
fi

# Publish to TestPyPI for validation (unless --skip-test is passed)
echo ""
echo "1️⃣  Publishing to TestPyPI (validation environment)..."
poetry publish -r testpypi --skip-existing
echo "✅ Published to TestPyPI"

# If --test-only, stop here
if [ "$TEST_ONLY" = true ]; then
    echo ""
    echo "📝 Test installation:"
    echo "   pip install --index-url https://test.pypi.org/simple/ mcp-server-jupyter==$VERSION"
    exit 0
fi

# Publish to production PyPI
echo ""
echo "2️⃣  Publishing to PyPI (PRODUCTION)..."
poetry publish --skip-existing
echo ""
echo "✅ Successfully published version $VERSION to PyPI!"
echo ""
echo "📝 Installation:"
echo "   pip install mcp-server-jupyter==$VERSION"
echo ""
echo "🔗 Package: https://pypi.org/project/mcp-server-jupyter/$VERSION/"
