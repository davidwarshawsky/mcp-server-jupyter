
#!/usr/bin/env node
/**
 * Script: inject-version.cjs
 * Purpose: Read the VERSION file and inject it into package.json and pyproject.toml.
 * This is a robust, portable replacement for the original inject-version.sh script.
 */

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.join(__dirname, '..');
const VERSION_FILE = path.join(REPO_ROOT, 'VERSION');

function log(message) {
  console.log(`[inject-version] ${message}`);
}

function error(message) {
  console.error(`[inject-version] ❌ ${message}`);
}

function updateJsonFile(filePath, version) {
  if (!fs.existsSync(filePath)) {
    log(`⚠️  ${path.basename(filePath)} not found, skipping.`);
    return;
  }
  log(`  → Updating ${path.basename(filePath)}`);
  const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  content.version = version;
  fs.writeFileSync(filePath, JSON.stringify(content, null, 2) + '\n');
}

function updateTomlFile(filePath, version) {
  if (!fs.existsSync(filePath)) {
    log(`⚠️  ${path.basename(filePath)} not found, skipping.`);
    return;
  }
  log(`  → Updating ${path.basename(filePath)}`);
  let content = fs.readFileSync(filePath, 'utf-8');
  content = content.replace(/^version = ".*?"/m, `version = "${version}"`);
  fs.writeFileSync(filePath, content);
}

function updatePythonFile(filePath, version) {
    if (!fs.existsSync(filePath)) {
        log(`ℹ️  ${path.basename(filePath)} not found, skipping (optional).`);
        return;
    }
    log(`  → Updating ${path.basename(filePath)}`);
    let content = fs.readFileSync(filePath, 'utf-8');
    content = content.replace(/^__version__ = ".*?"/m, `__version__ = "${version}"`);
    fs.writeFileSync(filePath, content);
}


function main() {
  if (!fs.existsSync(VERSION_FILE)) {
    error(`VERSION file not found at ${VERSION_FILE}`);
    process.exit(1);
  }

  const version = fs.readFileSync(VERSION_FILE, 'utf-8').trim();
  log(`📌 Injecting version: ${version}`);

  // 1. Update vscode-extension/package.json
  updateJsonFile(path.join(REPO_ROOT, 'vscode-extension', 'package.json'), version);

  // 2. Update tools/mcp-server-jupyter/pyproject.toml
  updateTomlFile(path.join(REPO_ROOT, 'tools', 'mcp-server-jupyter', 'pyproject.toml'), version);

  // 3. Update tools/mcp-server-jupyter/src/main.py
  updatePythonFile(path.join(REPO_ROOT, 'tools', 'mcp-server-jupyter', 'src', 'main.py'), version);
  
  // 4. Update tools/mcp-server-jupyter/src/tools/server_tools.py
  updatePythonFile(path.join(REPO_ROOT, 'tools', 'mcp-server-jupyter', 'src', 'tools', 'server_tools.py'), version);

  console.log('✅ Version injection complete.');
}

main();
