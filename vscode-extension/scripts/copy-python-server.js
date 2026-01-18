const fs = require('fs');
const path = require('path');

// Copy Python server to extension bundle
const sourceDir = path.join(__dirname, '..', '..', 'tools', 'mcp-server-jupyter');
const targetDir = path.join(__dirname, '..', 'python_server');

console.log('Copying Python server for extension packaging...');
console.log(`Source: ${sourceDir}`);
console.log(`Target: ${targetDir}`);

// Create target directory
if (fs.existsSync(targetDir)) {
  fs.rmSync(targetDir, { recursive: true, force: true });
}
fs.mkdirSync(targetDir, { recursive: true });

// Copy src directory (with filter to exclude cache files)
const srcSource = path.join(sourceDir, 'src');
const srcTarget = path.join(targetDir, 'src');

// Helper function to filter out unwanted files
function shouldCopyFile(src) {
  const name = path.basename(src);
  // Exclude __pycache__, .pyc files, .pytest_cache, .DS_Store
  if (name === '__pycache__' || name === '.pytest_cache' || name === '.DS_Store') {
    return false;
  }
  if (name.endsWith('.pyc') || name.endsWith('.pyo')) {
    return false;
  }
  return true;
}

// Recursive copy with filter
function copyDirFiltered(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }
  
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    
    if (!shouldCopyFile(srcPath)) {
      continue; // Skip this file/directory
    }
    
    if (entry.isDirectory()) {
      copyDirFiltered(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

copyDirFiltered(srcSource, srcTarget);
console.log('✓ Copied src/ (excluding __pycache__, .pyc, .DS_Store)');

// Copy essential files
const filesToCopy = [
  'pyproject.toml',
  'README.md',
  'uv.lock'
];

for (const file of filesToCopy) {
  const source = path.join(sourceDir, file);
  const target = path.join(targetDir, file);
  if (fs.existsSync(source)) {
    fs.copyFileSync(source, target);
    console.log(`✓ Copied ${file}`);
  } else {
    console.warn(`⚠ Skipped ${file} (not found)`);
  }
}

// Create requirements.txt from pyproject.toml dependencies
const pyprojectPath = path.join(sourceDir, 'pyproject.toml');
if (fs.existsSync(pyprojectPath)) {
  const pyproject = fs.readFileSync(pyprojectPath, 'utf-8');
  
  // Extract dependencies (simple parser)
  const depsMatch = pyproject.match(/dependencies\s*=\s*\[([\s\S]*?)\]/);
  if (depsMatch) {
    const deps = depsMatch[1]
      .split('\n')
      .map(line => line.trim())
      .filter(line => line.startsWith('"'))
      .map(line => line.replace(/[",]/g, '').trim())
      .filter(Boolean);
    
    const requirementsTxt = deps.join('\n') + '\n';
    fs.writeFileSync(path.join(targetDir, 'requirements.txt'), requirementsTxt);
    console.log('✓ Generated requirements.txt');
  }
}

console.log('✓ Python server bundled successfully!');
