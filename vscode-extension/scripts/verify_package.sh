#!/bin/bash
# Verify VSIX Package Integrity
#
# This script verifies that the distribution package (VSIX) actually contains
# all the necessary dependencies. A common failure mode is that wheels are
# downloaded but not included due to .vscodeignore misconfiguration.
#
# Run this before every release to ensure the "Fat VSIX" is actually fat.

set -e

echo "🔍 VSIX Package Verification"
echo "=============================="
echo ""

# Change to extension directory
cd "$(dirname "$0")/.."
echo "📁 Working directory: $(pwd)"
echo ""

# 1. Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -f *.vsix
rm -rf temp_verify

# 2. Run the packaging
echo "📦 Building VSIX package..."
npm run package

# Wait a moment for file system to catch up
sleep 1

# 3. Find the VSIX file
VSIX_FILE=$(ls -t *.vsix 2>/dev/null | head -1)
if [ -z "$VSIX_FILE" ]; then
    echo "❌ FAILURE: No VSIX file found!"
    echo "   Run 'npm run package' first."
    exit 1
fi

echo "✅ Found VSIX: $VSIX_FILE"
echo ""

# 4. Get VSIX size
VSIX_SIZE=$(du -h "$VSIX_FILE" | cut -f1)
echo "📊 VSIX size: $VSIX_SIZE"

# 5. Unzip the VSIX (it's just a zip) to a temp dir
echo "📂 Extracting VSIX contents..."
mkdir -p temp_verify
unzip -q "$VSIX_FILE" -d temp_verify

# 6. Verify structure
echo ""
echo "🔍 Verifying package structure..."

# Check for main extension files (TypeScript preserves src/ directory structure)
if [ ! -f "temp_verify/extension/out/src/extension.js" ]; then
    echo "❌ FAILURE: extension.js missing from VSIX!"
    echo "   Expected: extension/out/src/extension.js"
    exit 1
fi
echo "✅ Extension code found (out/src/extension.js)"

# Check for Python server
if [ ! -d "temp_verify/extension/python_server" ]; then
    echo "❌ FAILURE: python_server directory missing from VSIX!"
    exit 1
fi
echo "✅ Python server directory found"

# 7. Critical Check: Verify wheels directory exists
if [ ! -d "temp_verify/extension/python_server/wheels" ]; then
    echo "❌ FAILURE: wheels/ directory missing from VSIX!"
    echo ""
    echo "🔧 Troubleshooting:"
    echo "   1. Check your .vscodeignore file"
    echo "   2. Ensure 'python_server/wheels/**' is NOT in .vscodeignore"
    echo "   3. Run 'npm run download-wheels' before packaging"
    echo ""
    rm -rf temp_verify
    exit 1
fi
echo "✅ Wheels directory found"

# 8. Count wheels
WHEEL_COUNT=$(find temp_verify/extension/python_server/wheels -name "*.whl" 2>/dev/null | wc -l)
echo ""
echo "📊 Wheel Analysis:"
echo "   Found: $WHEEL_COUNT wheel files"

if [ "$WHEEL_COUNT" -lt 5 ]; then
    echo "❌ FAILURE: Not enough wheels found. Expected at least 5, got $WHEEL_COUNT."
    echo ""
    echo "🔧 Troubleshooting:"
    echo "   Run: npm run download-wheels"
    echo "   Check: python_server/wheels/ should contain:"
    echo "     - mcp (MCP SDK)"
    echo "     - pydantic (and pydantic-core)"
    echo "     - anyio, starlette, httpx, etc."
    echo ""
    rm -rf temp_verify
    exit 1
fi

# 9. List wheels for inspection
echo ""
echo "📦 Bundled wheels:"
find temp_verify/extension/python_server/wheels -name "*.whl" | while read wheel; do
    basename "$wheel"
done

# 10. Verify critical dependencies
echo ""
echo "🔍 Checking for critical dependencies..."

CRITICAL_PACKAGES=("mcp" "pydantic" "starlette" "anyio" "jupyter_client")
for pkg in "${CRITICAL_PACKAGES[@]}"; do
    if find temp_verify/extension/python_server/wheels -name "*${pkg}*.whl" | grep -q .; then
        echo "✅ Found: $pkg"
    else
        echo "⚠️  Warning: $pkg not found in wheels"
    fi
done

# 11. Check for Python server source code
echo ""
echo "🔍 Verifying Python server source..."
if [ ! -d "temp_verify/extension/python_server/src" ]; then
    echo "❌ FAILURE: Python server src/ directory missing!"
    rm -rf temp_verify
    exit 1
fi

if [ ! -f "temp_verify/extension/python_server/src/main.py" ]; then
    echo "❌ FAILURE: main.py missing from Python server!"
    rm -rf temp_verify
    exit 1
fi
echo "✅ Python server source code included"

# 12. Check for prompts (Superpower features)
if [ ! -d "temp_verify/extension/python_server/src/prompts" ]; then
    echo "⚠️  Warning: Prompts directory not found (Superpower features may be missing)"
else
    PROMPT_COUNT=$(find temp_verify/extension/python_server/src/prompts -name "*.md" | wc -l)
    echo "✅ Found $PROMPT_COUNT prompt files"
fi

# 13. Calculate total extracted size
EXTRACTED_SIZE=$(du -sh temp_verify | cut -f1)
echo ""
echo "📊 Package Statistics:"
echo "   VSIX size: $VSIX_SIZE"
echo "   Extracted size: $EXTRACTED_SIZE"
echo "   Wheel count: $WHEEL_COUNT"

# 14. Final verification
echo ""
echo "═══════════════════════════════════════"
echo "✅ SUCCESS: VSIX Package Verified!"
echo "═══════════════════════════════════════"
echo ""
echo "📦 This is a 'Fat VSIX' with $WHEEL_COUNT bundled dependencies"
echo "🚀 Ready for distribution"
echo ""
echo "Next steps:"
echo "  1. Test installation: code --install-extension $VSIX_FILE"
echo "  2. Run QA checklist: See QA_CHECKLIST.md"
echo "  3. Publish: vsce publish"

# 15. Cleanup
rm -rf temp_verify

echo ""
echo "🧹 Cleanup complete"
