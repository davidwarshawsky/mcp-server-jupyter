/**
 * scripts/record_simple.cjs
 * 
 * Simplified demo recorder using Playwright - CommonJS format
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const outputDir = path.join(__dirname, '..', 'docs', 'assets', 'demos');

async function takeScreenshots() {
  console.log('╔════════════════════════════════════════╗');
  console.log('║   MCP Jupyter Screenshot Recorder     ║');
  console.log('╚════════════════════════════════════════╝');
  console.log('');

  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 }
  });
  const page = await context.newPage();

  try {
    console.log('🌐 Opening code-server...');
    await page.goto('http://127.0.0.1:9091', { waitUntil: 'networkidle', timeout: 30000 });
    
    console.log('⏳ Waiting for VS Code to load...');
    await page.waitForTimeout(5000);
    
    // Take initial screenshot
    const welcomePath = path.join(outputDir, 'code-server-welcome.png');
    await page.screenshot({ path: welcomePath, fullPage: false });
    console.log(`📸 Screenshot saved: ${welcomePath}`);

    // Try to open a new file
    console.log('📓 Opening demo notebook via Command Palette...');
    await page.keyboard.press('Control+p');
    await page.waitForTimeout(1000);
    await page.keyboard.type('demo.ipynb');
    await page.waitForTimeout(500);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(3000);

    // Take screenshot of notebook
    const notebookPath = path.join(outputDir, 'demo-notebook.png');
    await page.screenshot({ path: notebookPath, fullPage: false });
    console.log(`📸 Screenshot saved: ${notebookPath}`);

    console.log('');
    console.log('✅ Screenshots complete!');

  } catch (error) {
    console.error('❌ Recording failed:', error.message);
    
    // Take debug screenshot
    const debugPath = path.join(outputDir, 'debug-error.png');
    await page.screenshot({ path: debugPath, fullPage: true });
    console.log(`📸 Debug screenshot saved: ${debugPath}`);
    
  } finally {
    await context.close();
    await browser.close();
  }
}

takeScreenshots().catch(console.error);
