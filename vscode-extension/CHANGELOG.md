# Changelog
All notable changes to the MCP Agent Kernel VSCode extension will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added - Week 4: Observability Dashboard
- **Execution View**: Real-time tree view showing active and completed cell executions
  - Live elapsed time tracking for running cells
  - Notebook name and cell index display
  - Auto-refresh every 2 seconds
  - Command: "MCP Jupyter: Refresh Executions"
- **Audit Log Viewer**: WebView panel for browsing execution history
  - Filter by kernel ID, event type (security/kernel/execution), or time range
  - Color-coded events (🔴 security, 🟢 kernel, 🔵 execution)
  - CSV export for compliance reporting
  - Command: "MCP Jupyter: Show Audit Log"
- **Asset Browser**: Preview images and PDFs inline (in progress)

### Added - Week 3: Error Transparency
- **Error Classification**: Automatic categorization of connection errors into 6 types
  - AUTH_FAILED: Invalid API key or authentication failure
  - NETWORK_ERROR: Connection timeout or network unreachable
  - SERVER_CRASH: Kernel died or server process crashed
  - PORT_IN_USE: Port conflict detected
  - TIMEOUT: Server not responding within configured timeout
  - UNKNOWN: Unclassified error with full details
- **Actionable Error Messages**: Step-by-step recovery guidance for each error type
  - "Check your credentials in settings.json"
  - "Verify server URL and firewall rules"
  - "Check server logs at ~/.mcp-jupyter/logs/server.log"
- **Privacy-Preserving Telemetry**: Logs to `.vscode/mcp-telemetry.jsonl`
  - No PII (personally identifiable information) collected
  - Connection success/failure events
  - Reconnection attempts with duration
  - Error classification results
  - Auto-rotation at 1000 entries
- **Telemetry Summary API**: Query telemetry for diagnostics
  - Total connections, failures, reconnections
  - Success rate percentage
  - Common failure reasons with counts

### Added - Week 2: One-Click Setup & Onboarding
- **Quick Start Command**: `MCP Jupyter: Quick Start` automates entire setup process
  - Three modes: Managed Environment (automatic), Existing Python, Remote Server
  - Guided wizard with progress indicators
  - Automatic dependency installation
  - Server verification and testing
- **Health Check Dashboard**: Real-time server status monitoring
  - WebSocket connection state
  - Python environment count
  - Server process status
  - Action buttons (Restart, Show Logs, Test Connection)
  - Auto-refresh every 2 seconds
- **Example Notebook**: Auto-generated quickstart guide with:
  - Basic execution examples
  - Variable inspection demos
  - Streaming output tests
  - Documentation links
- **Smart Setup Detection**: Skips setup if server already running
- **Quick Start Status Bar**: `$(rocket) Quick Start MCP` appears on first run
- **Better Error Messages**: Actionable guidance for common setup failures

### Added - Week 1: Connection Resilience
- **Automatic Reconnection**: Exponential backoff (1s → 32s) with jitter, up to 10 retry attempts
- **Heartbeat Monitoring**: WebSocket ping/pong every 30 seconds to detect stale connections
- **Connection Health Status Bar**: Real-time display of missed heartbeats and reconnection attempts
  - 🟢 `$(circle-filled) MCP` - Connected and healthy
  - ⚠️ `$(warning) MCP (2 missed)` - Connection degraded (missed heartbeats)
  - 🔄 `$(sync~spin) MCP (retry 3/10)` - Reconnecting with attempt counter
  - 🔴 `$(circle-outline) MCP` - Disconnected
- **Execution State Persistence**: Saves completed cell IDs to `.vscode/mcp-state.json` for recovery
- **Seamless Network Recovery**: Automatically reconnects after VPN switches, laptop sleep, or WiFi changes
- **Pending Request Preservation**: In-flight requests survive reconnections without resubmission
- **Configurable Reconnection**: Max attempts (10), base delay (1s), max delay (32s) configurable via private fields

### Changed
- WebSocket close handler now triggers automatic reconnection instead of showing error dialog immediately
- Connection state event emitter now fires health metrics (missed heartbeats, reconnect attempts)
- Status bar tooltip shows detailed connection state (e.g., "Connection unstable (2 missed heartbeats)")

### Technical Details
- Added `attemptReconnection()` method with exponential backoff and jitter
- Added `startHeartbeat()` / `stopHeartbeat()` methods for ping/pong monitoring
- Added `loadExecutionState()` / `saveExecutionState()` for client-side state persistence
- Added public `persistExecutionState()` / `restoreExecutionState()` methods for kernel provider integration
- Added `onConnectionHealthChange` event for UI updates

## [0.1.0] - 2025-01-15

### Added
- Initial release
- MCP Agent Kernel support for Jupyter notebooks
- Variable Dashboard with memory size display
- Asset-based output storage for large outputs (>2KB)
- Incremental output streaming
- Environment selection (conda, venv, system Python)
- Handoff protocol for human ↔ AI collaboration
- Auto-sync detection for external edits
- OpenTelemetry tracing support
- Security token authentication
- Connection status bar indicator
- Output channel logging

### Features
- Execute Python code cells in `.ipynb` files
- Real-time streaming of print statements and outputs
- Automatic kernel management (start on-demand, stop on close)
- Error handling with full traceback rendering
- Rich output support (text, HTML, images, JSON)
- Configurable polling interval (default: 500ms)
- Auto-restart on server crash (configurable)
- Manual server restart and environment selection commands

### Technical
- Built on Model Context Protocol (MCP)
- WebSocket transport with 'mcp' subprotocol
- JSON-RPC message format
- Notification throttling (max 10/sec) to prevent UI spam
- Version compatibility checking
