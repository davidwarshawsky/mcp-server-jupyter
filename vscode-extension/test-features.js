#!/usr/bin/env node
/**
 * Manual Test Script for Weeks 1-2 Features
 * Run with: node test-features.js
 */

const fs = require('fs');
const path = require('path');

console.log('🧪 Testing Weeks 1-2 Features\n');

// Test 1: Check if new files exist
console.log('Test 1: Verify new files exist');
const newFiles = [
  'src/quickStartWizard.ts',
  'src/healthCheckDashboard.ts',
  'src/test/reconnection.test.ts',
  'CHANGELOG.md'
];

let passed = 0;
let failed = 0;

newFiles.forEach(file => {
  const fullPath = path.join(__dirname, file);
  if (fs.existsSync(fullPath)) {
    console.log(`  ✅ ${file}`);
    passed++;
  } else {
    console.log(`  ❌ ${file} - NOT FOUND`);
    failed++;
  }
});

// Test 2: Check mcpClient has new methods
console.log('\nTest 2: Verify mcpClient.ts has new methods');
const mcpClientPath = path.join(__dirname, 'src/mcpClient.ts');
const mcpClientContent = fs.readFileSync(mcpClientPath, 'utf8');

const requiredMethods = [
  'attemptReconnection',
  'startHeartbeat',
  'stopHeartbeat',
  'persistExecutionState',
  'restoreExecutionState'
];

requiredMethods.forEach(method => {
  if (mcpClientContent.includes(`async ${method}`) || mcpClientContent.includes(`${method}(`)) {
    console.log(`  ✅ ${method}()`);
    passed++;
  } else {
    console.log(`  ❌ ${method}() - NOT FOUND`);
    failed++;
  }
});

// Test 3: Check for reconnection fields
console.log('\nTest 3: Verify reconnection state fields');
const reconnectionFields = [
  'reconnectAttempt',
  'maxReconnectAttempts',
  'baseReconnectDelay',
  'maxReconnectDelay',
  'heartbeatInterval',
  'lastPongReceived',
  'missedHeartbeats'
];

reconnectionFields.forEach(field => {
  if (mcpClientContent.includes(`private ${field}`)) {
    console.log(`  ✅ ${field}`);
    passed++;
  } else {
    console.log(`  ❌ ${field} - NOT FOUND`);
    failed++;
  }
});

// Test 4: Check package.json has new commands
console.log('\nTest 4: Verify package.json has new commands');
const packageJsonPath = path.join(__dirname, 'package.json');
const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));

const requiredCommands = [
  'mcp-jupyter.quickStart',
  'mcp-jupyter.showHealthCheck'
];

requiredCommands.forEach(cmd => {
  const found = packageJson.contributes.commands.some(c => c.command === cmd);
  if (found) {
    console.log(`  ✅ ${cmd}`);
    passed++;
  } else {
    console.log(`  ❌ ${cmd} - NOT FOUND`);
    failed++;
  }
});

// Test 5: Check extension.ts integration
console.log('\nTest 5: Verify extension.ts integration');
const extensionPath = path.join(__dirname, 'src/extension.ts');
const extensionContent = fs.readFileSync(extensionPath, 'utf8');

const integrationChecks = [
  { name: 'QuickStartWizard import', pattern: "import { QuickStartWizard }" },
  { name: 'HealthCheckDashboard import', pattern: "import { HealthCheckDashboard }" },
  { name: 'quickStartWizard variable', pattern: "let quickStartWizard" },
  { name: 'healthCheckDashboard variable', pattern: "let healthCheckDashboard" },
  { name: 'quickStart command registration', pattern: "mcp-jupyter.quickStart" },
  { name: 'onConnectionHealthChange subscription', pattern: "onConnectionHealthChange" }
];

integrationChecks.forEach(check => {
  if (extensionContent.includes(check.pattern)) {
    console.log(`  ✅ ${check.name}`);
    passed++;
  } else {
    console.log(`  ❌ ${check.name} - NOT FOUND`);
    failed++;
  }
});

// Test 6: Check notebookController has execution state persistence
console.log('\nTest 6: Verify notebookController.ts has persistence');
const controllerPath = path.join(__dirname, 'src/notebookController.ts');
const controllerContent = fs.readFileSync(controllerPath, 'utf8');

const persistenceChecks = [
  { name: 'persistExecutionState call', pattern: 'persistExecutionState' },
  { name: 'restoreExecutionState call', pattern: 'restoreExecutionState' },
  { name: 'completedCells tracking', pattern: 'this.completedCells' }
];

persistenceChecks.forEach(check => {
  if (controllerContent.includes(check.pattern)) {
    console.log(`  ✅ ${check.name}`);
    passed++;
  } else {
    console.log(`  ❌ ${check.name} - NOT FOUND`);
    failed++;
  }
});

// Test 7: Check README documentation
console.log('\nTest 7: Verify README documentation');
const readmePath = path.join(__dirname, 'README.md');
const readmeContent = fs.readFileSync(readmePath, 'utf8');

const docChecks = [
  { name: 'Week 1 features section', pattern: 'Week 1' },
  { name: 'Week 2 features section', pattern: 'Week 2' },
  { name: 'Connection Resilience', pattern: 'Connection Resilience' },
  { name: 'One-Click Setup', pattern: 'One-Click Setup' }
];

docChecks.forEach(check => {
  if (readmeContent.includes(check.pattern)) {
    console.log(`  ✅ ${check.name}`);
    passed++;
  } else {
    console.log(`  ❌ ${check.name} - NOT FOUND`);
    failed++;
  }
});

// Summary
console.log('\n' + '='.repeat(50));
console.log(`\n📊 Test Results: ${passed} passed, ${failed} failed`);
console.log(`   Success rate: ${Math.round((passed / (passed + failed)) * 100)}%\n`);

if (failed === 0) {
  console.log('✅ All tests passed! Features are properly integrated.\n');
  process.exit(0);
} else {
  console.log('⚠️  Some tests failed. Review the output above.\n');
  process.exit(1);
}
