#!/bin/bash
# Demo Recording Helper Script
# 
# This script manages the demo recording environment with code-server in Docker.
# 
# Usage:
#   ./run-demo.sh start     - Start code-server container
#   ./run-demo.sh stop      - Stop code-server container
#   ./run-demo.sh record    - Start container and run Playwright tests
#   ./run-demo.sh cleanup   - Stop container and clean up volumes
#   ./run-demo.sh shell     - Open a shell in the container
#   ./run-demo.sh logs      - View container logs
#   ./run-demo.sh status    - Check container status

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
CONTAINER_NAME="demo-code-server"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Export UID/GID for docker-compose (use different var names since UID is readonly in bash)
export DOCKER_UID=$(id -u)
export DOCKER_GID=$(id -g)

start_container() {
    log_info "Starting code-server container..."
    cd "$PROJECT_ROOT"
    docker compose -f "$COMPOSE_FILE" up -d
    
    log_info "Waiting for code-server to be ready..."
    local max_attempts=30
    local attempt=1
    
    while ! curl -s http://localhost:8443 > /dev/null 2>&1; do
        if [ $attempt -ge $max_attempts ]; then
            log_error "code-server failed to start after ${max_attempts} attempts"
            docker compose -f "$COMPOSE_FILE" logs
            exit 1
        fi
        echo -n "."
        sleep 2
        ((attempt++))
    done
    
    echo ""
    log_success "code-server is ready at http://localhost:8443"
}

stop_container() {
    log_info "Stopping code-server container..."
    cd "$PROJECT_ROOT"
    docker compose -f "$COMPOSE_FILE" down
    log_success "Container stopped"
}

run_recordings() {
    log_info "Starting demo recording session..."
    
    # Ensure container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        start_container
    fi
    
    # Create output directories
    mkdir -p "$SCRIPT_DIR/demo-recordings/screenshots"
    mkdir -p "$SCRIPT_DIR/demo-recordings/videos"
    
    log_info "Running Playwright tests..."
    cd "$PROJECT_ROOT"
    
    # Run Playwright with the demo config
    npx playwright test --config="$SCRIPT_DIR/playwright.demo.config.ts" "$@"
    
    log_success "Demo recordings saved to: $SCRIPT_DIR/demo-recordings/"
}

cleanup() {
    log_warn "This will stop the container and remove all persistent data."
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Cleaning up..."
        cd "$PROJECT_ROOT"
        docker compose -f "$COMPOSE_FILE" down -v
        
        # Remove local recording artifacts
        rm -rf "$SCRIPT_DIR/demo-recordings"
        
        log_success "Cleanup complete"
    else
        log_info "Cleanup cancelled"
    fi
}

show_logs() {
    docker compose -f "$COMPOSE_FILE" logs -f
}

open_shell() {
    log_info "Opening shell in code-server container..."
    docker exec -it "$CONTAINER_NAME" /bin/bash
}

show_status() {
    echo ""
    echo "=== Demo Recording Environment Status ==="
    echo ""
    
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_success "Container: Running"
        echo "  URL: http://localhost:8443"
        echo ""
        docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        log_warn "Container: Not running"
    fi
    
    echo ""
    echo "Volumes:"
    docker volume ls --filter "name=demo-code-server" --format "  - {{.Name}}" 2>/dev/null || echo "  (none)"
    
    echo ""
    echo "Recordings:"
    if [ -d "$SCRIPT_DIR/demo-recordings" ]; then
        find "$SCRIPT_DIR/demo-recordings" -name "*.webm" -o -name "*.mp4" 2>/dev/null | head -10
    else
        echo "  (no recordings yet)"
    fi
    echo ""
}

show_help() {
    echo "Demo Recording Helper Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  start     Start the code-server container"
    echo "  stop      Stop the code-server container"
    echo "  record    Start container and run Playwright demo tests"
    echo "  cleanup   Stop container and remove all persistent data"
    echo "  shell     Open a bash shell in the container"
    echo "  logs      View container logs (follow mode)"
    echo "  status    Show environment status"
    echo "  help      Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start                  # Start code-server"
    echo "  $0 record                 # Run all demo tests"
    echo "  $0 record --headed        # Run with visible browser"
    echo "  $0 record --grep 'MCP'    # Run only tests matching 'MCP'"
    echo ""
    echo "Environment:"
    echo "  CODE_SERVER_URL   Override the code-server URL (default: http://localhost:8443)"
    echo ""
}

# Main command dispatcher
case "${1:-help}" in
    start)
        start_container
        ;;
    stop)
        stop_container
        ;;
    record)
        shift
        run_recordings "$@"
        ;;
    cleanup)
        cleanup
        ;;
    logs)
        show_logs
        ;;
    shell)
        open_shell
        ;;
    status)
        show_status
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
