#!/bin/bash
# ==============================================================================
# Run All Demo Scenarios Sequentially
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$SCRIPT_DIR"

# Ensure container is running
if ! docker ps | grep -q demo-code-server; then
    echo "🚀 Starting demo container..."
    ./setup-demo.sh
fi

echo "🎬 Running all consolidated scenarios..."

# Run each scenario
# We use --project=chromium to be explicit, and --headed can be toggled if needed
# But for automated runs, we stick to defaults in config.

SCENARIOS=("scenario-01-setup.spec.ts" "scenario-02-standard.spec.ts" "scenario-03-superpowers.spec.ts")

for scenario in "${SCENARIOS[@]}"; do
    echo "------------------------------------------------------------"
    echo "▶️  Running: $scenario"
    echo "------------------------------------------------------------"
    if ! npx playwright test "demo-tests/$scenario" \
        --config=playwright.demo.config.ts \
        --timeout=180000; then
        echo "❌ Scenario $scenario failed!"
        exit 1
    fi
done

echo ""
echo "✅ All scenarios completed successfully!"
echo "📸 Screenshots are available in: scripts/demo-recording/demo-recordings/screenshots/"
