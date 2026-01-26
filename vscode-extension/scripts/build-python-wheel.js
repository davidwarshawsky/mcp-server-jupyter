const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// Build a wheel from the Python server package and copy the wheel into the
// extension bundle. This ensures the extension consumes an immutable artifact
// (wheel) instead of raw source files.

const repoRoot = path.join(__dirname, '..', '..');
const serverDir = path.join(repoRoot, 'tools', 'mcp-server-jupyter');
const distDir = path.join(serverDir, 'dist');
const targetDir = path.join(__dirname, '..', 'python_server');

function run(cmd, opts = {}) {
  console.log('> ' + cmd);
  return execSync(cmd, { stdio: 'inherit', env: process.env, ...opts });
}

try {
  console.log('Building Python wheel for MCP server...');

  // Step 1: Inject unified version from VERSION file
  console.log('📌 Injecting unified version from VERSION file...');
  try {
    run(`bash "${path.join(repoRoot, 'scripts', 'inject-version.sh')}"`);
  } catch (e) {
    console.warn('⚠️  Version injection failed (non-fatal, continuing):', e.message);
  }

  if (!fs.existsSync(serverDir)) {
    throw new Error(`Server directory not found: ${serverDir}`);
  }

  // Clean dist
  if (fs.existsSync(distDir)) {
    fs.rmSync(distDir, { recursive: true, force: true });
  }
  fs.mkdirSync(distDir, { recursive: true });

  // Prefer poetry if available and pyproject.toml exists
  const pyproject = path.join(serverDir, 'pyproject.toml');
  let built = false;

  try {
    if (fs.existsSync(pyproject)) {
      console.log('pyproject.toml found — attempting to build wheel via poetry...');
      // Try poetry build
      run(`cd "${serverDir}" && poetry build -f wheel -o dist`);
      built = true;
    }
  } catch (e) {
    console.warn('poetry build failed or poetry not available — falling back to python -m build');
  }

  if (!built) {
    try {
      // Use PEP517 build via python -m build (requires 'build' package)
      run(`cd "${serverDir}" && python -m build --wheel --outdir dist`);
      built = true;
    } catch (e) {
      console.error('Wheel build failed. Ensure poetry or python-build is available.');
      throw e;
    }
  }

  // Find wheel
  const wheels = fs.readdirSync(distDir).filter(f => f.endsWith('.whl'));
  if (wheels.length === 0) {
    throw new Error('No wheel file found in dist/. Build must produce a .whl');
  }

  // Use the newest wheel (sorted by mtime)
  wheels.sort((a, b) => {
    const aStat = fs.statSync(path.join(distDir, a));
    const bStat = fs.statSync(path.join(distDir, b));
    return bStat.mtimeMs - aStat.mtimeMs;
  });

  const wheelFile = path.join(distDir, wheels[0]);
  console.log(`Found wheel: ${wheelFile}`);

  // Prepare target directory
  if (fs.existsSync(targetDir)) {
    fs.rmSync(targetDir, { recursive: true, force: true });
  }
  fs.mkdirSync(targetDir, { recursive: true });

  // Copy wheel into target
  const targetWheel = path.join(targetDir, path.basename(wheelFile));
  fs.copyFileSync(wheelFile, targetWheel);
  console.log(`Copied wheel to ${targetWheel}`);

  // Write a short README explaining why we ship a wheel
  fs.writeFileSync(path.join(targetDir, 'README.txt'), 'This directory contains a built wheel of the MCP Python server.\nInstall into your environment with: pip install <wheel-file>\n');

  console.log('✓ Built and bundled Python wheel for extension');
} catch (err) {
  console.error('✗ Failed to build Python wheel:', err);
  process.exit(1);
}
