const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

console.log('Generating SBOM...');

const NPM_BOM_PATH = 'bom.npm.json';
const PY_BOM_PATH = 'bom.py.json';
const FINAL_BOM_PATH = 'bom.json';

const cleanup = () => {
  if (fs.existsSync(NPM_BOM_PATH)) fs.unlinkSync(NPM_BOM_PATH);
  if (fs.existsSync(PY_BOM_PATH)) fs.unlinkSync(PY_BOM_PATH);
};

try {
  // 1. Generate SBOM for npm dependencies (including workspaces)
  console.log('Generating SBOM for npm components...');
  execSync(`npx @cyclonedx/bom -o ${NPM_BOM_PATH} --output-format json`, {
    stdio: 'inherit',
  });

  // 2. Generate SBOM for Python dependencies
  console.log('Generating SBOM for Python components...');
  execSync(
    `poetry run cyclonedx-py --format json -o ${PY_BOM_PATH}`,
    {
      stdio: 'inherit',
      cwd: path.join(__dirname, '..', 'tools', 'mcp-server-jupyter'),
    }
  );

  // 3. Merge SBOMs
  console.log('Merging SBOMs...');
  const npmBom = JSON.parse(fs.readFileSync(NPM_BOM_PATH, 'utf8'));
  const pyBom = JSON.parse(fs.readFileSync(PY_BOM_PATH, 'utf8'));

  // A real implementation would be more robust, handling component merging, etc.
  // For now, we are concatenating the component lists which is a good starting point.
  const mergedBom = {
    ...npmBom,
    components: [...(npmBom.components || []), ...(pyBom.components || [])],
    metadata: {
      ...npmBom.metadata,
      // Add information about the merge
      properties: [
        {
          name: 'bom:merge:strategy',
          value: 'concatenate',
        },
        {
          name: 'bom:merge:tool',
          value: 'custom-script',
        },
      ],
    },
  };

  // Update serial number to a new UUID
  mergedBom.serialNumber = `urn:uuid:${require('crypto').randomUUID()}`;
  // Update timestamp
  mergedBom.metadata.timestamp = new Date().toISOString();

  fs.writeFileSync(FINAL_BOM_PATH, JSON.stringify(mergedBom, null, 2));

  console.log(`Successfully generated merged SBOM at ${FINAL_BOM_PATH}`);
} catch (error) {
  console.error('Failed to generate SBOM:', error);
  process.exit(1);
} finally {
  // 4. Clean up intermediate files
  cleanup();
}
