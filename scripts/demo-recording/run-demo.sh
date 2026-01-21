#!/bin/bash
# ==============================================================================
# Run Demo Recording Tests
# ==============================================================================
#
# Usage: ./run-demo.sh [test-name]
#
# Examples:
#   ./run-demo.sh                    # Run all demo tests
#   ./run-demo.sh duckdb-magic       # Run specific test
#
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Check if container is running
if ! docker ps | grep -q demo-code-server; then
    echo "❌ Demo container not running. Run ./setup-demo.sh first."
    exit 1
fi

# Check if code-server is accessible
if ! curl -s http://localhost:8443 > /dev/null 2>&1; then
    echo "❌ code-server not accessible at http://localhost:8443"
    exit 1
fi

echo "🎬 Running demo recording tests..."
echo ""

# Determine which test to run
if [ -n "$1" ]; then
    TEST_FILE="scripts/demo-recording/demo-tests/${1}.spec.ts"
    if [ ! -f "$TEST_FILE" ]; then
        TEST_FILE="scripts/demo-recording/demo-tests/${1}"
    fi
else
    TEST_FILE="scripts/demo-recording/demo-tests/duckdb-magic.spec.ts"
fi

echo "   Test: $TEST_FILE"
echo ""

# Run Playwright
npx playwright test "$TEST_FILE" \
    --config=scripts/demo-recording/playwright.demo.config.ts \
    --timeout=120000 \
    "$@"

echo ""
echo "✅ Demo recording complete!"
echo ""
echo "   Screenshots: scripts/demo-recording/demo-recordings/"
echo "   Report:      npx playwright show-report scripts/demo-recording/demo-recordings/report"
