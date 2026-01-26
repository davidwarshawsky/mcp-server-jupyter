#!/bin/bash
# Security Verification Script
# Validates that all critical security patches are applied

echo "🔐 MCP Jupyter Server - Security Verification"
echo "=============================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS=0
FAIL=0

check_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((PASS++))
}

check_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((FAIL++))
}

check_warn() {
    echo -e "${YELLOW}⚠️  WARN${NC}: $1"
}

echo "📋 Running Security Checks..."
echo ""

# Check 1: SQL Injection Protection
echo "1. Checking SQL Injection Protection (data_tools.py)..."
if grep -q "base64.b64encode(sql_query.encode())" src/data_tools.py && \
   grep -q 'base64.b64decode("{encoded_query}").decode()' src/data_tools.py; then
    check_pass "Base64 encoding/decoding present"
else
    check_fail "SQL injection protection missing"
fi

# Check 2: Package Allowlist
echo "2. Checking Package Allowlist (environment.py)..."
if grep -q "PACKAGE_ALLOWLIST = {" src/environment.py; then
    PACKAGE_COUNT=$(grep -A 30 "^PACKAGE_ALLOWLIST = {" src/environment.py | grep -oE "'[a-z0-9-]+'" | wc -l)
    if [ "$PACKAGE_COUNT" -ge 25 ]; then
        check_pass "Package allowlist defined with $PACKAGE_COUNT packages"
    else
        check_warn "Package allowlist only has $PACKAGE_COUNT packages (expected 25+)"
    fi
else
    check_fail "Package allowlist not found"
fi

# Check 3: Wildcard Override for Enterprise
echo "3. Checking Enterprise Override Support..."
if grep -q 'allowlist_str.strip() == '"'"'*'"'"'' src/environment.py; then
    check_pass "Wildcard override for enterprise deployments present"
else
    check_warn "Enterprise wildcard override missing"
fi

# Check 4: File Locking (Split-Brain Prevention)
echo "4. Checking File Locking Implementation..."
if grep -q "portalocker.Lock" src/session.py || grep -q "fcntl.flock" src/session.py; then
    check_pass "File locking mechanism present"
else
    check_warn "File locking not detected (may use alternative method)"
fi

# Check 5: DAG Executor
echo "5. Checking DAG-Based Smart Sync..."
if [ -f "src/dag_executor.py" ]; then
    if grep -q "def get_minimal_rerun_set" src/dag_executor.py; then
        check_pass "DAG executor with minimal rerun logic present"
    else
        check_warn "DAG executor exists but minimal rerun logic unclear"
    fi
else
    check_fail "DAG executor missing"
fi

# Check 6: No Obvious Secrets
echo "6. Scanning for Hardcoded Secrets..."
SECRETS_FOUND=0
for pattern in "password.*=.*['\"]" "api_key.*=.*['\"]" "secret.*=.*['\"]" "token.*=.*['\"]"; do
    if grep -rE "$pattern" src/ --exclude="*.pyc" --exclude-dir="__pycache__" 2>/dev/null | grep -v "# Example" | grep -v "# TODO" | grep -v "test_" > /dev/null; then
        SECRETS_FOUND=1
    fi
done

if [ $SECRETS_FOUND -eq 0 ]; then
    check_pass "No hardcoded secrets detected"
else
    check_warn "Potential hardcoded secrets found (manual review needed)"
fi

# Check 7: Syntax Validation
echo "7. Running Python Syntax Checks..."
if python3 -m py_compile src/*.py 2>/dev/null; then
    check_pass "All Python files have valid syntax"
else
    check_fail "Syntax errors detected in Python files"
fi

# Check 8: Dependencies Security
echo "8. Checking for Known Vulnerable Dependencies..."
if command -v pip-audit &> /dev/null; then
    if pip-audit --requirement <(poetry export -f requirements.txt --without-hashes) &> /dev/null; then
        check_pass "No known vulnerabilities in dependencies"
    else
        check_warn "Vulnerabilities found (run 'pip-audit' for details)"
    fi
else
    check_warn "pip-audit not installed (skipping dependency check)"
fi

# Summary
echo ""
echo "=============================================="
echo "📊 Security Verification Summary"
echo "=============================================="
echo -e "Passed: ${GREEN}$PASS${NC}"
echo -e "Failed: ${RED}$FAIL${NC}"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}🎉 All critical security checks passed!${NC}"
    echo "Ready for production deployment."
    exit 0
else
    echo -e "${RED}❌ $FAIL critical security checks failed!${NC}"
    echo "Fix issues before deploying to production."
    exit 1
fi
