#!/bin/bash
# Phase 1: Immediate Stabilization Validation Script
# Run this after deployment to verify critical functionality

set -e

echo "🛑 Phase 1: Immediate Stabilization Check"
echo "=========================================="
echo ""

# 1.1. Verify install_package Ambiguity Fixed
echo "✅ 1.1. Checking install_package definitions..."
INSTALL_PACKAGE_COUNT=$(grep -A 1 "@mcp.tool()" src/main.py | grep -c "async def install_package" || echo "0")

if [ "$INSTALL_PACKAGE_COUNT" -eq 1 ]; then
    echo "   ✓ Exactly 1 install_package definition found"
    grep -B 1 "async def install_package" src/main.py | head -4
else
    echo "   ✗ ERROR: Found $INSTALL_PACKAGE_COUNT install_package definitions (expected 1)"
    echo "   Manual intervention required."
    exit 1
fi

echo ""

# 1.2. Verify kernel_startup.py is included in packaging
echo "✅ 1.2. Checking kernel_startup.py packaging..."

if [ -f "src/kernel_startup.py" ]; then
    echo "   ✓ kernel_startup.py exists in src/"
else
    echo "   ✗ ERROR: kernel_startup.py not found in src/"
    exit 1
fi

if grep -q "kernel_startup.py" MANIFEST.in; then
    echo "   ✓ kernel_startup.py declared in MANIFEST.in"
else
    echo "   ⚠ WARNING: kernel_startup.py not explicitly listed in MANIFEST.in"
    echo "   This may cause packaging issues with PyInstaller/VSIX"
fi

# Check if get_startup_code is imported in session.py
if grep -q "from src.kernel_startup import" src/session.py; then
    echo "   ✓ kernel_startup imported in session.py"
else
    echo "   ✗ ERROR: kernel_startup not imported in session.py"
    exit 1
fi

echo ""

# 1.3. Verify Circuit Breaker Implementation
echo "✅ 1.3. Checking circuit breaker logic..."

if grep -q "listener_consecutive_errors" src/session.py; then
    echo "   ✓ Circuit breaker tracking found"
else
    echo "   ✗ ERROR: Circuit breaker tracking not found"
    exit 1
fi

if grep -q "listener_consecutive_errors.*= 0" src/session.py; then
    echo "   ✓ Circuit breaker reset on success implemented"
else
    echo "   ⚠ WARNING: Circuit breaker may not reset on success"
    echo "   This could cause false positives after transient errors"
fi

if grep -q "consecutive_errors >= 5" src/session.py; then
    echo "   ✓ Circuit breaker trip threshold: 5 errors"
else
    echo "   ⚠ WARNING: Circuit breaker threshold not configured"
fi

echo ""

# Additional Checks
echo "🔍 Additional Integrity Checks..."

# Check SHA-256 usage (not MD5)
if grep -q "hashlib.sha256" src/utils.py; then
    echo "   ✓ SHA-256 in use (FIPS compliant)"
else
    echo "   ⚠ WARNING: SHA-256 not found in utils.py"
fi

# Check atomic backpressure (put_nowait)
if grep -q "put_nowait" src/session.py; then
    echo "   ✓ Atomic backpressure with put_nowait()"
else
    echo "   ⚠ WARNING: May still use racy .full() check"
fi

# Check __pycache__ filter in copy script
if [ -f "../vscode-extension/scripts/copy-python-server.js" ]; then
    if grep -q "__pycache__" ../vscode-extension/scripts/copy-python-server.js; then
        echo "   ✓ Copy script filters __pycache__"
    else
        echo "   ⚠ WARNING: copy-python-server.js may not filter cache files"
    fi
else
    echo "   ⚠ INFO: VS Code extension not found (standalone Python server mode)"
fi

echo ""
echo "=========================================="
echo "✅ Phase 1 Validation Complete"
echo ""
echo "Next Steps:"
echo "1. Run integration tests: pytest tests/"
echo "2. Test kernel injection: Start kernel and run '_mcp_inspect(\"x\")'"
echo "3. Monitor logs for circuit breaker behavior under load"
echo ""
echo "If all checks passed, proceed to Phase 2: Architectural Refactoring"
