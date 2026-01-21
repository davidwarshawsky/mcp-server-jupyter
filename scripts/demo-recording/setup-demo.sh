#!/bin/bash
# ==============================================================================
# MCP Jupyter Demo Recording Environment Setup Script
# ==============================================================================
#
# This script sets up a complete demo recording environment with a single command.
# It handles Docker, extension building, and all configuration.
#
# Usage: ./setup-demo.sh [--rebuild] [--clean]
#
# Options:
#   --rebuild   Force rebuild the Docker image
#   --clean     Remove all volumes and start fresh
#
# ==============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXTENSION_DIR="$PROJECT_ROOT/vscode-extension"

# Parse arguments
REBUILD=false
CLEAN=false
for arg in "$@"; do
    case $arg in
        --rebuild)
            REBUILD=true
            shift
            ;;
        --clean)
            CLEAN=true
            shift
            ;;
    esac
done

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     MCP Jupyter Demo Recording Environment Setup          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

cd "$SCRIPT_DIR"

# Step 1: Clean if requested
if [ "$CLEAN" = true ]; then
    echo -e "${YELLOW}🧹 Cleaning up old environment...${NC}"
    docker compose down -v 2>/dev/null || true
    rm -rf /tmp/mcp-ext
    echo -e "${GREEN}   ✓ Cleanup complete${NC}"
fi

# Step 2: Build or rebuild Docker image
if [ "$REBUILD" = true ] || ! docker images | grep -q "demo-code-server-custom"; then
    echo -e "${YELLOW}🐳 Building Docker image...${NC}"
    docker compose build
    echo -e "${GREEN}   ✓ Docker image built${NC}"
else
    echo -e "${GREEN}   ✓ Docker image already exists (use --rebuild to force)${NC}"
fi

# Step 3: Start container
echo -e "${YELLOW}🚀 Starting container...${NC}"
docker compose up -d
echo -e "${GREEN}   ✓ Container started${NC}"

# Step 4: Wait for container to be ready
echo -e "${YELLOW}⏳ Waiting for code-server to be ready...${NC}"
for i in {1..30}; do
    if curl -s http://localhost:8443 > /dev/null 2>&1; then
        echo -e "${GREEN}   ✓ code-server is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}   ✗ code-server not responding after 30 seconds${NC}"
        exit 1
    fi
    sleep 1
done

# Step 5: Install Jupyter and Python extensions
echo -e "${YELLOW}📦 Installing Jupyter and Python extensions...${NC}"
docker exec demo-code-server /app/code-server/bin/code-server \
    --install-extension ms-toolsai.jupyter \
    --install-extension ms-python.python \
    2>/dev/null || true
echo -e "${GREEN}   ✓ Core extensions installed${NC}"

# Step 6: Build MCP extension
echo -e "${YELLOW}🔧 Building MCP Agent Kernel extension...${NC}"
cd "$EXTENSION_DIR"
npm run bundle-python > /dev/null 2>&1
npm run compile > /dev/null 2>&1
npm run build:renderer > /dev/null 2>&1
npx vsce package > /dev/null 2>&1
echo -e "${GREEN}   ✓ Extension built: $(ls -1 mcp-agent-kernel-*.vsix | head -1)${NC}"

# Step 7: Install MCP extension
echo -e "${YELLOW}📥 Installing MCP extension in container...${NC}"
rm -rf /tmp/mcp-ext
mkdir -p /tmp/mcp-ext
unzip -q mcp-agent-kernel-*.vsix -d /tmp/mcp-ext
docker exec demo-code-server rm -rf /config/extensions/warshawsky-research.mcp-agent-kernel-0.1.0 2>/dev/null || true
docker cp /tmp/mcp-ext/extension demo-code-server:/config/extensions/warshawsky-research.mcp-agent-kernel-0.1.0
echo -e "${GREEN}   ✓ MCP extension installed${NC}"

# Step 8: Restart container to load extensions
echo -e "${YELLOW}🔄 Restarting container to load extensions...${NC}"
cd "$SCRIPT_DIR"
docker compose restart
sleep 5
echo -e "${GREEN}   ✓ Container restarted${NC}"

# Step 9: Verify everything is working
echo -e "${YELLOW}🔍 Verifying setup...${NC}"
sleep 5

# Check if code-server is running
if curl -s http://localhost:8443 > /dev/null 2>&1; then
    echo -e "${GREEN}   ✓ code-server accessible at http://localhost:8443${NC}"
else
    echo -e "${RED}   ✗ code-server not accessible${NC}"
    exit 1
fi

# Check if extensions are installed
EXT_COUNT=$(docker exec demo-code-server ls /config/extensions | wc -l)
echo -e "${GREEN}   ✓ ${EXT_COUNT} extensions installed${NC}"

# Check if demo notebook exists
if docker exec demo-code-server test -f /config/workspace/demo.ipynb; then
    echo -e "${GREEN}   ✓ demo.ipynb mounted${NC}"
else
    echo -e "${RED}   ✗ demo.ipynb not found${NC}"
fi

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                    Setup Complete! 🎉                       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}Access VS Code:${NC}    http://localhost:8443"
echo -e "  ${GREEN}Run Playwright:${NC}   npx playwright test demo-tests/duckdb-magic.spec.ts"
echo -e "  ${GREEN}View Logs:${NC}        docker logs demo-code-server"
echo -e "  ${GREEN}Stop:${NC}             docker compose down"
echo ""
echo -e "${YELLOW}Tip:${NC} Wait a few seconds for extensions to fully initialize before running tests."
echo ""
