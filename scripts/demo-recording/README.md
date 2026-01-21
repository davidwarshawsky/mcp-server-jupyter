# 🎬 Demo Recording Environment

This directory contains everything needed to create polished demo recordings of MCP Jupyter.

## 🚀 Quick Start

```bash
# One command to set everything up
./setup-demo.sh

# Run the demo test
./run-demo.sh
```

## 📁 Directory Structure

```
demo-recording/
├── setup-demo.sh              # 🔧 One-command setup script
├── run-demo.sh                # ▶️  Run Playwright tests
├── Dockerfile                 # 🐳 Custom container image
├── docker-compose.yml         # 🐙 Container orchestration
├── automation-config/
│   └── settings.json          # ⚙️  VS Code settings for demos
├── demo-tests/
│   └── duckdb-magic.spec.ts   # 🧪 Playwright test script
├── demo-recordings/           # 📸 Output screenshots/videos
├── LESSONS_LEARNED.md         # 📚 Deep dive on debugging
├── PROGRESS_PLAN_...md        # 📋 Project tracking
└── README.md                  # 📖 This file
```

## 🎯 What You Get

After running `./setup-demo.sh`, you'll have:

- ✅ **code-server** running at http://localhost:8443
- ✅ **Jupyter extension** installed and configured
- ✅ **MCP Agent Kernel extension** with all fixes applied
- ✅ **Python 3** with data science packages (pandas, numpy, matplotlib)
- ✅ **demo.ipynb** mounted and ready
- ✅ **Dark theme** for beautiful screenshots

## 📺 Creating Demos

### Automated (Playwright)

```bash
./run-demo.sh                     # Run all demo tests
./run-demo.sh duckdb-magic        # Run specific test
```

Output goes to `demo-recordings/`.

### Manual

1. Open http://localhost:8443
2. Navigate to `demo.ipynb`
3. Select "🤖 MCP Agent Kernel"
4. Record with OBS Studio or similar

## 🔧 Configuration

### VS Code Settings (`automation-config/settings.json`)

Key settings for demo environment:

```json
{
  "workbench.startupEditor": "none",       // No welcome page
  "security.workspace.trust.enabled": false, // No trust prompts
  "mcp-jupyter.showSetupWizard": false,    // No auto-install wizard
  "mcp-jupyter.autoStart": true,           // Server starts automatically
  "window.zoomLevel": 1,                   // Larger text for recordings
  "workbench.colorTheme": "Default Dark Modern"
}
```

### Docker Resources

Adjust in `docker-compose.yml`:

```yaml
mem_limit: 4g    # Memory limit
cpus: 2.0        # CPU limit
shm_size: 2gb    # Shared memory
```

## 🔄 Workflow

### Fresh Start

```bash
# Clean everything and rebuild
./setup-demo.sh --clean --rebuild
```

### Quick Iteration

```bash
# Just run tests (container already running)
./run-demo.sh

# After changing extension code:
cd ../../vscode-extension
npm run bundle-python && npm run compile && npx vsce package
./setup-demo.sh  # Will reinstall extension
```

### Stop Environment

```bash
cd scripts/demo-recording
docker compose down      # Stop container, keep data
docker compose down -v   # Stop and delete all data
```

## 🐛 Troubleshooting

### Container not starting?

```bash
docker compose logs -f
```

### Extension not loading?

```bash
docker exec demo-code-server ls /config/extensions
```

### Server connection errors?

```bash
# Check MCP server logs
docker exec demo-code-server find /config/data/logs -name "1-MCP Jupyter Server.log" -exec cat {} \;
```

### Need fresh state?

```bash
./setup-demo.sh --clean
```

## 📚 Deep Dive

See [LESSONS_LEARNED.md](LESSONS_LEARNED.md) for:
- All bugs encountered and how they were fixed
- WebSocket authentication details
- VS Code extension debugging tips
- Playwright selector strategies

## 🎥 Output Assets

After running demos, find outputs in:

- `demo-recordings/` - Screenshots and videos
- `docs/media/` - Published assets for README

### Moving Assets to Docs

```bash
cp demo-recordings/duckdb-magic*/test-finished-1.png ../../docs/media/hero-demo.png
cp demo-recordings/duckdb-magic*/video.webm ../../docs/media/demo-video.webm
```
