# Integration Testing Guide

## Overview

We have three layers of testing:

1. **Unit Tests (Python)** - Server logic in isolation ✅ (120+ tests)
2. **Integration Tests (TypeScript)** - Extension ↔ Server communication ✅ (NEW)
3. **Manual QA** - Real-world user scenarios ✅ (NEW)

This guide explains how to run the **Integration Tests** that prove the VS Code extension can actually spawn and control the Python server.

---

## Why Integration Tests Matter

**The Problem**: Unit tests can pass green while the product is dead on arrival.

Examples:
- ✅ Python tests pass
- ❌ But `subprocess.spawn()` fails on Windows due to path quoting
- ❌ But WebSocket handshake times out in Electron
- ❌ But wheels are missing from VSIX package

**The Solution**: Integration tests that run the **real stack**:
- Real VS Code instance (via `@vscode/test-electron`)
- Real TypeScript extension code
- Real Python server (spawned as subprocess)
- Real WebSocket communication

---

## Running Integration Tests

### Prerequisites

1. **VS Code Extension Development Setup**:
   ```bash
   cd vscode-extension
   npm install
   npm run compile
   ```

2. **Python Server Available**:
   ```bash
   cd tools/mcp-server-jupyter
   pip install -e .
   # Or use uv/poetry
   ```

### Run All Integration Tests

```bash
cd vscode-extension
npm test
```

This will:
1. Download a headless VS Code instance (first run only)
2. Launch VS Code with your extension
3. Run all tests in `src/test/suite/server_integration.test.ts`
4. Report pass/fail for each test

**Expected output**:
```
🔧 Setting up integration test environment...
📦 Activating extension...
✅ Extension activated and configured

  Real Server Integration Test Suite
    ✓ Proof of Life: Server Spawns and Responds (8234ms)
    ✓ Windows Compatibility: Subprocess Spawning Works (1245ms)
    ✓ WebSocket Handshake: Full Duplex Communication (4521ms)
    ✓ Superpower Check: Query DataFrames Tool Registered (823ms)
    ✓ Error Recovery: Server Recovers from Bad Code (3412ms)
    ✓ Asset Offloading: Large Output Handled Gracefully (5123ms)

  6 passing (25s)
```

---

## What Each Test Verifies

### Test 1: Proof of Life
**Tests**: Basic subprocess spawning and code execution

**Failure Modes**:
- `spawn ENOENT` (Python not found)
- `EACCES` (permission issues)
- Timeout (server didn't start in 30s)

### Test 2: Windows Compatibility
**Tests**: Path quoting, environment variables, stdio piping

**Failure Modes**:
- Windows path with spaces breaks spawn command
- Environment variables not inherited
- Stdout/stderr not captured

### Test 3: WebSocket Handshake
**Tests**: Bidirectional communication with streaming

**Failure Modes**:
- WebSocket upgrade fails
- Streaming output not received
- Connection drops during execution

### Test 4: Superpower Check
**Tests**: MCP protocol tool registration

**Failure Modes**:
- Tools not registered (`query_dataframes`, `save_checkpoint`, etc.)
- MCP protocol version mismatch
- Tool schema validation fails

### Test 5: Error Recovery
**Tests**: Kernel resilience after crashes

**Failure Modes**:
- Kernel hangs after error
- Extension doesn't recover
- Error messages not propagated

### Test 6: Asset Offloading
**Tests**: Large output handling

**Failure Modes**:
- VS Code freezes with 10MB+ output
- Extension crashes
- Memory leak from unbounded buffers

---

## Debugging Integration Test Failures

### Enable Verbose Logging

Edit `src/test/suite/server_integration.test.ts`:

```typescript
setup(async () => {
    // Add this line:
    process.env.MCP_LOG_LEVEL = 'DEBUG';
    
    // ... rest of setup
});
```

### View Server Logs

During tests, server logs go to:
- macOS/Linux: `~/.vscode-test/logs/`
- Windows: `%APPDATA%\Code\logs\`

Look for files like `exthost*.log` and `main*.log`.

### Run Single Test

```bash
cd vscode-extension
npm test -- --grep "Proof of Life"
```

### Manual Debugging

1. Add `debugger;` statement in test
2. Run: `code --extensionDevelopmentPath=/path/to/vscode-extension --extensionTestsPath=/path/to/test/suite/index.js`
3. Attach VS Code debugger (F5 in second VS Code instance)

---

## Verifying VSIX Package Integrity

Before releasing, verify the VSIX actually contains all dependencies:

```bash
cd vscode-extension
./scripts/verify_package.sh
```

**This script checks**:
1. ✅ VSIX file exists and has reasonable size (5-15 MB)
2. ✅ `python_server/wheels/` directory included
3. ✅ At least 5 wheel files present
4. ✅ Critical packages: mcp, pydantic, jupyter_client, starlette, anyio
5. ✅ Python server source code (`src/main.py`) included
6. ✅ Prompt files (Superpower features) included

**Expected output**:
```
🔍 VSIX Package Verification
==============================

📦 Building VSIX package...
✅ Found VSIX: mcp-agent-kernel-1.0.0.vsix
📊 VSIX size: 12M

🔍 Verifying package structure...
✅ Extension code found
✅ Python server directory found
✅ Wheels directory found

📊 Wheel Analysis:
   Found: 8 wheel files

📦 Bundled wheels:
mcp-0.9.0-py3-none-any.whl
pydantic-2.6.1-py3-none-any.whl
pydantic_core-2.16.2-cp312-cp312-macosx_11_0_arm64.whl
...

═══════════════════════════════════════
✅ SUCCESS: VSIX Package Verified!
═══════════════════════════════════════

📦 This is a 'Fat VSIX' with 8 bundled dependencies
🚀 Ready for distribution
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Integration Tests

on: [push, pull_request]

jobs:
  test-integration:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Node
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install Extension Dependencies
        run: |
          cd vscode-extension
          npm install
      
      - name: Install Python Server
        run: |
          cd tools/mcp-server-jupyter
          pip install -e .
      
      - name: Run Integration Tests
        run: |
          cd vscode-extension
          npm test
        env:
          DISPLAY: ':99.0' # Linux headless display
      
      - name: Verify VSIX Package
        run: |
          cd vscode-extension
          ./scripts/verify_package.sh
```

---

## Common Issues & Solutions

### Issue: "Extension host did not start in 10 seconds"

**Solution**: Increase timeout in test setup:
```typescript
this.timeout(60000); // 60 seconds
```

### Issue: "Server not found" on Windows

**Solution**: Verify Python is in PATH:
```typescript
const pythonPath = process.platform === 'win32' 
    ? 'python.exe' 
    : 'python3';
```

### Issue: Tests pass locally but fail in CI

**Solution**: CI environments often lack display server. Use xvfb on Linux:
```bash
xvfb-run -a npm test
```

### Issue: WebSocket connection refused

**Solution**: Check firewall settings and ensure port is available:
```typescript
const port = await getAvailablePort(3000, 4000);
```

---

## Manual QA Checklist

After integration tests pass, run the **Manual QA Checklist**:

```bash
cd vscode-extension
cat QA_CHECKLIST.md
```

Key manual tests:
1. ✅ Clean install on fresh machine
2. ✅ "No Python" error path
3. ✅ Superpower features work (DuckDB, Auto-EDA, Time Travel)
4. ✅ Cross-platform testing (macOS, Windows, Linux)

---

## Test Coverage Summary

| Layer | Tool | Coverage | Files |
|-------|------|----------|-------|
| Python Unit Tests | pytest | 120+ tests | `tools/mcp-server-jupyter/tests/` |
| Integration Tests | VS Code Test | 6 tests | `vscode-extension/src/test/suite/` |
| Package Verification | Bash script | 1 check | `vscode-extension/scripts/verify_package.sh` |
| Manual QA | Human checklist | 10 scenarios | `vscode-extension/QA_CHECKLIST.md` |

---

## Success Criteria

Before releasing to production:

- [ ] All Python unit tests pass (120+)
- [ ] All integration tests pass (6)
- [ ] Package verification script succeeds
- [ ] Manual QA checklist completed on 2+ platforms
- [ ] No critical bugs in issue tracker

**When all checked**: 🚀 **Ready to ship!**

---

## Next Steps

1. **Run Integration Tests**:
   ```bash
   cd vscode-extension && npm test
   ```

2. **Verify Package**:
   ```bash
   ./scripts/verify_package.sh
   ```

3. **Run Manual QA**:
   - Follow `QA_CHECKLIST.md`
   - Test on your primary platform
   - File any bugs found

4. **Ship It**:
   ```bash
   vsce publish
   ```

---

**Last Updated**: 2026-01-15  
**Integration Tests Version**: 1.0
