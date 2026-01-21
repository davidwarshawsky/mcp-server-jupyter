# Demo Recording Environment

This directory contains the setup for recording Playwright demo videos of Jupyter notebooks in an isolated code-server Docker environment.

## Why Docker?

Running code-server directly on the host causes problems:
- Restarting code-server kills any active VS Code sessions
- Configuration conflicts between demo and development
- Difficult to reset to a clean state

The Docker approach provides:
- **Isolation**: Demo environment is completely separate from your development setup
- **Reproducibility**: Start fresh each time with consistent state
- **Safety**: Won't interfere with any running VS Code sessions

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Host Machine                         │
│                                                              │
│  ┌────────────────────┐     ┌─────────────────────────────┐ │
│  │                    │     │     Docker Container        │ │
│  │    Playwright      │────▶│                             │ │
│  │   (runs locally)   │     │    code-server:latest       │ │
│  │                    │     │    http://localhost:8443    │ │
│  │  - Controls Chrome │     │                             │ │
│  │  - Records video   │     │    /home/coder/project      │ │
│  │  - Captures UI     │     │         ▲                   │ │
│  └────────────────────┘     │         │                   │ │
│                             └─────────│───────────────────┘ │
│                                       │                      │
│  ┌────────────────────────────────────┴──────────────────┐  │
│  │              Your Project Files (mounted)              │  │
│  │              ~/personal/mcp-server-jupyter             │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Start the demo environment
./run-demo.sh start

# 2. Open in browser to verify (optional)
open http://localhost:8443

# 3. Run demo recordings
./run-demo.sh record

# 4. Stop when done
./run-demo.sh stop
```

## Files

| File | Description |
|------|-------------|
| `docker-compose.yml` | Docker Compose configuration for code-server |
| `playwright.demo.config.ts` | Playwright configuration optimized for demo recordings |
| `run-demo.sh` | Helper script for managing the demo environment |
| `demo-tests/` | Directory containing Playwright test files for demos |
| `demo-recordings/` | Output directory for videos, screenshots, and reports |

## Commands

### `./run-demo.sh start`
Starts the code-server container and waits for it to be ready.

### `./run-demo.sh stop`
Stops the code-server container.

### `./run-demo.sh record [playwright-args]`
Starts the container (if needed) and runs the Playwright demo tests.

```bash
# Run all demo tests
./run-demo.sh record

# Run with visible browser
./run-demo.sh record --headed

# Run specific test
./run-demo.sh record --grep "notebook"

# Run in debug mode
./run-demo.sh record --debug
```

### `./run-demo.sh cleanup`
Stops the container and removes all persistent data (volumes, recordings).

### `./run-demo.sh status`
Shows the current status of the demo environment.

### `./run-demo.sh logs`
Shows container logs (follow mode).

### `./run-demo.sh shell`
Opens a bash shell inside the container.

## Configuration

### Docker Compose (`docker-compose.yml`)

Key settings:
- **Port 8443**: code-server web UI
- **No authentication**: `--auth=none` for automated testing
- **Volume mounts**: Project files available at `/home/coder/project`
- **Persistent volumes**: Extensions and settings persist across restarts

### Playwright Config (`playwright.demo.config.ts`)

Key settings:
- **Video**: Always on, 1920x1080 resolution
- **Viewport**: Matches video size for crisp output
- **Single worker**: Sequential execution for predictable recordings
- **webServer**: Automatically starts/stops Docker container

## Writing Demo Tests

Demo tests are regular Playwright tests but optimized for recording:

```typescript
import { test, expect } from '@playwright/test';

test('demo: create and run notebook', async ({ page }) => {
  // Navigate to code-server
  await page.goto('/');
  
  // Wait for VS Code to load
  await page.waitForSelector('.monaco-workbench', { timeout: 60000 });
  
  // Your demo steps...
  await page.keyboard.press('Control+Shift+P');
  await page.keyboard.type('Jupyter: Create New Notebook');
  await page.keyboard.press('Enter');
  
  // Pause for visibility in the recording
  await page.waitForTimeout(2000);
});
```

### Tips for Good Demo Recordings

1. **Add pauses**: Use `waitForTimeout()` after important actions so viewers can see what happened
2. **Use explicit waits**: Always wait for elements before interacting
3. **Keep it focused**: Each test should demonstrate one concept
4. **Add comments**: The test file serves as documentation

## Troubleshooting

### Container won't start
```bash
# Check Docker logs
./run-demo.sh logs

# Check if port 8443 is in use
lsof -i :8443
```

### VS Code takes too long to load
- First load can take 30-60 seconds as extensions initialize
- Subsequent loads are faster due to cached data in volumes

### Video quality issues
- Ensure viewport matches video size (default: 1920x1080)
- Check `shm_size` in docker-compose.yml (default: 2gb)

### Permission issues with mounted files
- The container runs as your UID/GID
- If issues persist, check the `UID` and `GID` environment variables

### Resetting to clean state
```bash
# Remove all persistent data
./run-demo.sh cleanup

# Start fresh
./run-demo.sh start
```

## Advanced Configuration

### Installing VS Code Extensions

Extensions persist in the `code-server-local` volume. To pre-install:

```bash
# Start container
./run-demo.sh start

# Install extensions
docker exec demo-code-server code-server --install-extension ms-python.python
docker exec demo-code-server code-server --install-extension ms-toolsai.jupyter

# Stop and restart to apply
./run-demo.sh stop
./run-demo.sh start
```

### Custom code-server Settings

Settings persist in the `code-server-config` volume at:
- `/home/coder/.config/code-server/config.yaml`
- `/home/coder/.local/share/code-server/User/settings.json`

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CODE_SERVER_URL` | `http://localhost:8443` | Override code-server URL |
| `UID` | Current user's UID | Container user ID |
| `GID` | Current user's GID | Container group ID |
