# Fat VSIX - Quick Reference Card

## 🚀 Build Commands

```bash
# Development
cd vscode-extension
npm install                   # Install dependencies
npm run bundle-python        # Copy Python server (always required)
npm run bundle-wheels        # Download wheels (~2 min, ~26 MB)
npm run compile              # Compile TypeScript

# Production
npm run package              # Fat VSIX (30 MB, offline support)
npm run package:thin         # Thin VSIX (3 MB, online only)
```

---

## 📦 What Gets Bundled

### Fat VSIX (30 MB)
```
mcp-agent-kernel-1.0.0.vsix/
├── extension.js           (TypeScript compiled)
├── python_server/
│   ├── src/              (Server code)
│   ├── pyproject.toml
│   └── wheels/           ← 69 wheel files (26 MB)
│       ├── fastmcp-*.whl
│       ├── pydantic-*.whl
│       └── jupyter_client-*.whl
```

### Thin VSIX (3 MB)
```
mcp-agent-kernel-1.0.0.vsix/
├── extension.js
├── python_server/
│   ├── src/
│   └── pyproject.toml
```

---

## 🔍 Verification Commands

```bash
# Check wheel bundle
ls -lh vscode-extension/python_server/wheels/
# Expected: 69 .whl files, ~26 MB total

# Check VSIX contents
unzip -l mcp-agent-kernel-1.0.0.vsix | grep wheels
# Should show: python_server/wheels/*.whl files

# Test offline detection
node -e "const fs = require('fs'); const p = 'vscode-extension/python_server/wheels'; console.log(fs.existsSync(p) && fs.readdirSync(p).length > 0)"
# Expected: true (Fat VSIX) or false (Thin VSIX)

# Run tests
npm test --silent
# Expected: 7 passing
```

---

## 🎯 Installation Modes

### Online Installation (Both VSIX Types)
```
User installs VSIX → Setup Wizard → Managed Env → pip install
                                                      ↓
                                              ┌───────┴────────┐
                                              │                │
                                          Fat VSIX         Thin VSIX
                                              ↓                ↓
                                  pip install --no-index   pip install
                                  --find-links=wheels/     (downloads from PyPI)
                                              ↓                ↓
                                          ✅ 30s            ⚠️ 2-5 min
```

### Offline Installation (Fat VSIX Only)
```
User installs VSIX → Setup Wizard → Managed Env → pip install --no-index
                                                              ↓
                                                    Uses bundled wheels
                                                              ↓
                                                          ✅ 30s
                                                    (No network needed)
```

---

## 📊 Size Comparison

| Component | Thin VSIX | Fat VSIX | Notes |
|-----------|-----------|----------|-------|
| Extension code | 2 MB | 2 MB | Same |
| Python server | 1 MB | 1 MB | Same |
| Wheel bundle | 0 MB | 26 MB | **Fat only** |
| **Total** | **3 MB** | **29 MB** | 10x larger |

---

## 🛠️ Build Matrix

| Command | Bundles Wheels? | VSIX Size | Use Case |
|---------|----------------|-----------|----------|
| `npm run compile` | No | N/A | Development |
| `npm run package` | **Yes** | 30 MB | **Production/Offline** |
| `npm run package:thin` | No | 3 MB | Online-only |

---

## ✅ Health Checks

### Before Building
```bash
# Check Python available
python --version  # Should be 3.9+

# Check Node available
node --version    # Should be 18+

# Check disk space
df -h vscode-extension/python_server  # Need 30 MB free
```

### After Building (Fat VSIX)
```bash
# 1. Wheel count
find vscode-extension/python_server/wheels -name "*.whl" | wc -l
# Expected: 69

# 2. Bundle size
du -sh vscode-extension/python_server/wheels
# Expected: ~26M

# 3. VSIX size
ls -lh vscode-extension/*.vsix
# Expected: ~30M

# 4. Test compilation
cd vscode-extension && npm run compile
# Expected: No errors

# 5. Test suite
npm test --silent
# Expected: 7 passing
```

---

## 🐛 Troubleshooting

### Issue: `bundle_wheels.sh` fails
```bash
# Windows: Use Git Bash
bash scripts/bundle_wheels.sh

# Linux/Mac: Check permissions
chmod +x scripts/bundle_wheels.sh
./scripts/bundle_wheels.sh

# Error: "pip: command not found"
python -m pip --version  # Use python -m pip
```

### Issue: Wheels directory empty (0 files)
```bash
# Check pip version
pip --version  # Should be 22.0+

# Upgrade pip
python -m pip install --upgrade pip

# Re-run bundling
npm run bundle-wheels
```

### Issue: VSIX > 50 MB (too large)
```bash
# Check wheel count
find vscode-extension/python_server/wheels -name "*.whl" | wc -l

# If > 100 wheels, platform duplication occurred
# Solution: Clean and re-run
rm -rf vscode-extension/python_server/wheels
npm run bundle-wheels
```

### Issue: Offline install fails
```bash
# Check wheels exist in VSIX
unzip -l mcp-agent-kernel-*.vsix | grep wheels | wc -l
# Expected: 69 lines

# Check setupManager.ts logic
grep -A 5 "hasLocalWheels" vscode-extension/src/setupManager.ts
# Should find: fs.existsSync(wheelsDir)
```

---

## 📝 Quick Deploy Checklist

- [ ] Run `npm run bundle-python`
- [ ] Run `npm run bundle-wheels` (wait ~2 min)
- [ ] Verify 69 wheels exist
- [ ] Run `npm test --silent` (7 passing)
- [ ] Run `npm run package`
- [ ] Check VSIX size (<30 MB)
- [ ] Test install on clean VM (optional)
- [ ] Generate SHA256: `sha256sum *.vsix > checksums.txt`
- [ ] Ship! 🚀

---

## 🔗 Related Docs

- **Deep Dive:** [FAT_VSIX_GUIDE.md](FAT_VSIX_GUIDE.md)
- **Checklist:** [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)
- **Summary:** [FAT_VSIX_SUMMARY.md](FAT_VSIX_SUMMARY.md)
- **README Template:** [README_ENHANCEMENT_TEMPLATE.md](README_ENHANCEMENT_TEMPLATE.md)

---

## 🎓 Key Concepts

### What is a "Fat VSIX"?
A VS Code extension package (.vsix) that **bundles all Python dependencies as wheel files**, eliminating the need for internet access during installation.

### Why "Fat"?
Because it's **10x larger** than a standard VSIX (30 MB vs. 3 MB) due to the included wheel files.

### When to use Fat VSIX?
- ✅ Public marketplace release (supports all users)
- ✅ Enterprise deployment (firewalls, air-gaps)
- ✅ Offline/restricted environments
- ✅ Maximum reliability (no PyPI dependency)

### When to use Thin VSIX?
- ⚠️ Internal deployment with reliable internet
- ⚠️ Bandwidth-constrained downloads
- ⚠️ You want to force users to have latest deps (but this breaks offline)

**Recommendation:** Always ship Fat VSIX for public releases.

---

## 💡 Pro Tips

1. **Parallel Builds:** Bundle wheels once, compile many times
   ```bash
   npm run bundle-wheels  # Once per dependency change
   npm run compile        # Many times during dev
   ```

2. **Size Optimization:** Remove unused platforms
   ```bash
   # Edit scripts/bundle_wheels.sh
   PLATFORMS=("manylinux2014_x86_64" "win_amd64")  # Only Linux + Windows
   ```

3. **Verify Before Publishing:**
   ```bash
   # Unpack VSIX and inspect
   unzip -d test_unpack mcp-agent-kernel-1.0.0.vsix
   ls test_unpack/extension/python_server/wheels/
   ```

4. **Test Both Modes:**
   ```bash
   npm run package        # Test Fat VSIX
   npm run package:thin   # Test Thin VSIX
   # Install both, compare behavior
   ```

---

## 🎯 Success Criteria

✅ **Fat VSIX is ready when:**
- [ ] `bundle_wheels.sh` runs without errors
- [ ] `python_server/wheels/` has 60-80 .whl files
- [ ] VSIX size is 20-35 MB
- [ ] Offline install shows "(Offline Mode)"
- [ ] All 7 tests pass
- [ ] Can install with network disabled

---

**Last Updated:** January 15, 2026  
**Version:** 1.0.0-rc1  
**Status:** ✅ Implementation Complete
