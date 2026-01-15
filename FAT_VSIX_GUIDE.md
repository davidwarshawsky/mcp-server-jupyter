# Fat VSIX Distribution Guide

## Overview

This extension supports **two distribution modes** to accommodate different deployment environments:

| Mode | Description | Use Case |
|------|-------------|----------|
| **Fat VSIX** (Offline) | Bundles Python dependencies as wheel files inside the extension | Corporate firewalls, air-gapped machines, restricted networks |
| **Thin VSIX** (Online) | Downloads dependencies from PyPI during installation | Standard deployments with internet access |

---

## Why Fat VSIX?

### Enterprise Challenges
- **Firewalls**: Corporate networks often block direct access to `pypi.org`
- **Air-Gapped Machines**: Research/security systems have no internet connectivity
- **Reliability**: `pip install` can fail due to network issues or package availability
- **Compliance**: Some organizations require pre-approved, vendored dependencies

### Fat VSIX Guarantees
✅ If the VSIX installs, the server **will work** (no network required)  
✅ Consistent behavior across all environments  
✅ No runtime dependency resolution failures  
✅ Faster installation (no downloads during setup)

---

## Building the Fat VSIX

### Prerequisites
- Node.js 18+ and npm
- Python 3.9+ with pip
- Bash shell (Linux/macOS) or Git Bash (Windows)

### Build Steps

#### 1. Bundle Python Dependencies
```bash
cd vscode-extension
npm run bundle-wheels
```

This downloads platform-specific wheel files for:
- **Linux**: x86_64, ARM64 (manylinux2014)
- **Windows**: 64-bit (win_amd64)
- **macOS**: Intel (x86_64), Apple Silicon (arm64)

**Output:**
```
📦 Downloading dependencies for multiple platforms...
  → manylinux2014_x86_64
  → manylinux2014_aarch64
  → win_amd64
  → macosx_11_0_arm64
  → macosx_11_0_x86_64

✅ Wheel bundling complete!
  Location: vscode-extension/python_server/wheels
  Files: 42 wheels
```

#### 2. Package the Extension
```bash
npm run package
```

This runs:
1. `bundle-python` - Copies Python server source
2. `bundle-wheels` - Downloads wheel files
3. `compile` - Compiles TypeScript
4. `vsce package` - Creates the `.vsix` file

**Output:** `mcp-agent-kernel-<version>.vsix` (Fat VSIX, ~10-20 MB)

---

## Building the Thin VSIX (Optional)

If you prefer a smaller package for standard deployments:

```bash
npm run package:thin
```

This **skips** wheel bundling, resulting in a ~2-3 MB VSIX that requires internet access during installation.

---

## Installation Behavior

### Fat VSIX Installation Flow

```
User installs .vsix
    ↓
Extension activates
    ↓
Setup Wizard opens (first run)
    ↓
User selects "Managed Environment"
    ↓
Extension creates Python venv
    ↓
setupManager.installDependencies() detects local wheels
    ↓
Runs: pip install --no-index --find-links=wheels/ python_server/
    ↓
✅ Installation complete (no PyPI access needed)
```

### Thin VSIX Installation Flow

```
User installs .vsix
    ↓
Extension activates
    ↓
Setup Wizard opens (first run)
    ↓
User selects "Managed Environment"
    ↓
Extension creates Python venv
    ↓
setupManager.installDependencies() (no local wheels)
    ↓
Runs: pip install python_server/
    ↓
Downloads dependencies from PyPI
    ↓
✅ Installation complete (requires internet)
```

---

## Verification

### Check for Bundled Wheels
```bash
ls -lh vscode-extension/python_server/wheels/
```

Expected output:
```
total 12M
-rw-r--r-- 1 user user 1.2M fastmcp-0.1.0-py3-none-any.whl
-rw-r--r-- 1 user user 890K pydantic-2.x.x-py3-none-any.whl
-rw-r--r-- 1 user user 3.1M jupyter_client-8.x.x-py3-none-any.whl
...
```

### Test Offline Installation
1. **Disable Network:**
   ```bash
   # Linux/macOS
   sudo ifconfig eth0 down
   
   # Windows
   # Disable network adapter in Settings
   ```

2. **Install VSIX:**
   - Open VS Code
   - Extensions → `...` → Install from VSIX
   - Select `mcp-agent-kernel-<version>.vsix`

3. **Run Setup Wizard:**
   - Command Palette → "MCP Jupyter: Open Setup Wizard"
   - Complete steps 1-3
   - ✅ Should succeed without network access

4. **Re-enable Network**

---

## Troubleshooting

### Issue: `bundle_wheels.sh` Fails on Windows

**Solution:** Use Git Bash or WSL:
```bash
# Git Bash
bash scripts/bundle_wheels.sh

# WSL
wsl bash scripts/bundle_wheels.sh
```

### Issue: Wheel Download Fails

**Error:** `ERROR: Could not find a version that satisfies the requirement...`

**Solution:** Update pip and try again:
```bash
python -m pip install --upgrade pip
npm run bundle-wheels
```

### Issue: VSIX is Too Large (>100 MB)

**Cause:** Too many platform variants or large dependencies

**Solution:** Reduce platform coverage in `bundle_wheels.sh`:
```bash
# Only bundle for Linux x86_64 and Windows
PLATFORMS=(
    "manylinux2014_x86_64"
    "win_amd64"
)
```

### Issue: User Reports "Installation Failed" in Air-Gapped Environment

**Debug Steps:**
1. Verify wheels exist in VSIX:
   ```bash
   unzip -l mcp-agent-kernel-<version>.vsix | grep wheels
   ```
2. Check extension logs:
   - VS Code → Output → "MCP Jupyter Server"
3. Verify pip version in managed venv:
   ```bash
   <venv>/bin/python -m pip --version
   ```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Build and Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build-fat-vsix:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          cd vscode-extension
          npm ci
      
      - name: Bundle wheels
        run: |
          cd vscode-extension
          npm run bundle-wheels
      
      - name: Package extension
        run: |
          cd vscode-extension
          npm run package
      
      - name: Upload VSIX
        uses: actions/upload-artifact@v3
        with:
          name: mcp-agent-kernel-fat.vsix
          path: vscode-extension/*.vsix
```

---

## Size Comparison

| Mode | Size | Contents |
|------|------|----------|
| **Thin VSIX** | ~2-3 MB | TypeScript/JS code only |
| **Fat VSIX** | ~10-20 MB | Code + Python wheels (all platforms) |
| **Fat VSIX (Linux only)** | ~8-12 MB | Code + Linux wheels only |

---

## Security Considerations

### Wheel Verification
The bundled wheels are downloaded from PyPI and are **not modified**. To verify integrity:

```bash
pip download --hash-check <package>==<version>
```

### Supply Chain Security
- All dependencies are pinned in `pyproject.toml`
- Wheels include cryptographic signatures from PyPI
- Use `pip-audit` to scan for vulnerabilities:
  ```bash
  pip-audit -r tools/mcp-server-jupyter/pyproject.toml
  ```

---

## Best Practices

### For Public Release (VS Code Marketplace)
- ✅ Use **Fat VSIX** (supports all environments)
- ✅ Include wheels for all major platforms
- ✅ Test on clean Windows/Linux/macOS VMs

### For Internal Deployment
- If network is reliable: **Thin VSIX** (smaller download)
- If network is restricted: **Fat VSIX**
- Consider platform-specific builds to reduce size

### For Air-Gapped Deployment
- ✅ Always use **Fat VSIX**
- ✅ Test installation with network disabled
- ✅ Provide SHA256 checksums for verification

---

## Maintenance

### Updating Dependencies
When you update Python dependencies in `pyproject.toml`:

1. Update the server:
   ```bash
   cd tools/mcp-server-jupyter
   pip install -e .
   ```

2. Re-bundle wheels:
   ```bash
   cd vscode-extension
   npm run bundle-wheels
   ```

3. Re-package extension:
   ```bash
   npm run package
   ```

### Monitoring Wheel Size
Track wheel bundle size over time:
```bash
du -sh vscode-extension/python_server/wheels/
```

If size grows significantly (>50 MB), consider:
- Removing unused dependencies
- Using platform-specific builds
- Splitting into multiple VSIXs

---

## FAQ

**Q: Can I ship both Fat and Thin VSIXs?**  
A: Yes! Build both and let users choose. Name them clearly:
- `mcp-agent-kernel-v1.0.0-fat.vsix` (offline)
- `mcp-agent-kernel-v1.0.0.vsix` (online)

**Q: Does the Fat VSIX work with Python 3.13+?**  
A: Update `PYTHON_VERSIONS` in `bundle_wheels.sh` to include newer versions.

**Q: What if a platform-specific wheel isn't available?**  
A: The script will warn you. Either:
- Exclude that platform
- Accept source distributions (requires compiler at install time)

**Q: How do I verify the extension uses local wheels?**  
A: Check the progress notification during setup:
- Fat VSIX: "Installing MCP Server Dependencies **(Offline Mode)**"
- Thin VSIX: "Installing MCP Server Dependencies"

---

## Summary

The Fat VSIX strategy ensures your extension works **anywhere**, from Google's corporate network to a research submarine's air-gapped laptop.

**Deployment Checklist:**
- [ ] Run `npm run bundle-wheels` successfully
- [ ] Verify wheels exist in `python_server/wheels/`
- [ ] Test installation with network disabled
- [ ] Check VSIX size (<30 MB ideal)
- [ ] Document offline installation in README
- [ ] Include SHA256 checksums in release notes

**You're now ready for Google-Grade distribution! 🚀**
