#!/bin/bash
set -e

echo "═══════════════════════════════════════════════════════════════"
echo "🚀 MCP Jupyter Server - Pre-flight Checks"
echo "═══════════════════════════════════════════════════════════════"

# ─────────────────────────────────────────────────────────────────
# 1. ZOMBIE KILLER: Clean up stale processes
# ─────────────────────────────────────────────────────────────────
echo ""
echo "🔍 Checking for stale processes..."

# Kill any process holding port 3000 from previous crashes
# This prevents "Address already in use" errors on rapid restarts
if command -v fuser >/dev/null 2>&1; then
    echo "  Checking port 3000..."
    fuser -k 3000/tcp >/dev/null 2>&1 || true
    echo "  ✓ Port 3000 cleared"
else
    echo "  ⚠ fuser not available, skipping port cleanup"
fi

# Kill any stale python processes from previous crashes
# (only if they're not the current shell)
if command -v pkill >/dev/null 2>&1; then
    echo "  Checking for orphaned Python processes..."
    pkill -f "python.*mcp-server" || true
    sleep 1
    echo "  ✓ Orphaned processes cleaned"
fi

# ─────────────────────────────────────────────────────────────────
# 2. LOCK FILE CLEANUP
# ─────────────────────────────────────────────────────────────────
echo ""
echo "🧹 Cleaning up stale lock files..."

if [ -d "${MCP_DATA_DIR:-/data/mcp}" ]; then
    DATA_DIR="${MCP_DATA_DIR:-/data/mcp}"
    LOCK_COUNT=$(find "$DATA_DIR" -name "*.lock" 2>/dev/null | wc -l)
    
    if [ "$LOCK_COUNT" -gt 0 ]; then
        echo "  Found $LOCK_COUNT stale lock files"
        find "$DATA_DIR" -name "*.lock" -delete 2>/dev/null || true
        echo "  ✓ Lock files removed"
    else
        echo "  ✓ No stale locks found"
    fi
else
    echo "  ⚠ MCP_DATA_DIR not set or doesn't exist"
fi

# ─────────────────────────────────────────────────────────────────
# 3. FILESYSTEM PERMISSIONS
# ─────────────────────────────────────────────────────────────────
echo ""
echo "🔐 Ensuring filesystem permissions..."

# If volumes are mounted by the host or orchestration they may be owned by root; handle gracefully
# This fixes permission issues on restarts
if [ -d "${MCP_DATA_DIR:-/data/mcp}" ]; then
    DATA_DIR="${MCP_DATA_DIR:-/data/mcp}"
    
    # Only attempt if we're running as root (typical in containers)
    if [ "$(id -u)" = "0" ]; then
        # Assume 'appuser' or 'jupyter' user exists (from Dockerfile)
        if id appuser >/dev/null 2>&1; then
            chown -R appuser:appuser "$DATA_DIR" 2>/dev/null || true
            echo "  ✓ Data directory owned by appuser"
        elif id jupyter >/dev/null 2>&1; then
            chown -R jupyter:jupyter "$DATA_DIR" 2>/dev/null || true
            echo "  ✓ Data directory owned by jupyter"
        else
            echo "  ⚠ No app user found for permission fix"
        fi
    else
        echo "  ℹ Not running as root, skipping permission fix"
    fi
else
    echo "  ⚠ Data directory not configured"
fi

# ─────────────────────────────────────────────────────────────────
# 4. ENVIRONMENT VALIDATION
# ─────────────────────────────────────────────────────────────────
echo ""
echo "✓ Environment variables:"

echo "  MCP_DATA_DIR: ${MCP_DATA_DIR:-/data/mcp}"
echo "  MCP_MAX_KERNELS: ${MCP_MAX_KERNELS:-10}"
echo "  MCP_MAX_QUEUE_SIZE: ${MCP_MAX_QUEUE_SIZE:-1000}"

# Validate Python installation
echo ""
echo "✓ Python Configuration:"
python --version
python -c "import sys; print(f'  Executable: {sys.executable}')"
python -c "import sys; print(f'  Path: {sys.prefix}')"

# ─────────────────────────────────────────────────────────────────
# 5. DATABASE VALIDATION
# ─────────────────────────────────────────────────────────────────
echo ""
echo "✓ Database Check:"

DB_PATH="${MCP_DATA_DIR:-/data/mcp}/sessions/state.db"
if [ -f "$DB_PATH" ]; then
    echo "  Found: $DB_PATH"
    # Quick SQLite integrity check
    if python -c "import sqlite3; sqlite3.connect('$DB_PATH').execute('PRAGMA integrity_check')" >/dev/null 2>&1; then
        echo "  ✓ Database integrity OK"
    else
        echo "  ⚠ Database integrity check failed (will auto-recover on startup)"
    fi
else
    echo "  ℹ Database will be created on first run"
fi

# ─────────────────────────────────────────────────────────────────
# 6. MEMORY CHECK (for large workloads)
# ─────────────────────────────────────────────────────────────────
echo ""
echo "✓ System Resources:"

if command -v free >/dev/null 2>&1; then
    TOTAL_MEM=$(free -m | awk '/^Mem:/ {print $2}')
    echo "  Total Memory: ${TOTAL_MEM} MB"
fi

if [ -f /proc/cpuinfo ]; then
    CPU_COUNT=$(grep -c ^processor /proc/cpuinfo)
    echo "  CPU Cores: $CPU_COUNT"
fi

# ─────────────────────────────────────────────────────────────────
# 7. SIGNAL HANDLERS (graceful shutdown)
# ─────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "✨ All pre-flight checks passed!"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Set signal handlers for graceful shutdown
trap 'echo "Received SIGTERM, shutting down gracefully..."; exit 0' SIGTERM
trap 'echo "Received SIGINT, shutting down gracefully..."; exit 0' SIGINT

# ─────────────────────────────────────────────────────────────────
# 8. START SERVER
# ─────────────────────────────────────────────────────────────────
echo "🎯 Starting MCP Jupyter Server..."
echo ""

# Use exec to replace this shell with the server process
# This ensures PID 1 = server (proper container behavior)
exec python -m src.main "$@"

# Note: If we get here, something went wrong with exec
echo "ERROR: Failed to start server"
exit 1
