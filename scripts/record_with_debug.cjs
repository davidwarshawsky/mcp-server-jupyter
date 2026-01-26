/**
 * scripts/record_with_debug.cjs
 * 
 * Debug version that captures console output and handles trust dialog properly
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const outputDir = path.join(__dirname, '..', 'docs', 'assets', 'demos');
const CODE_SERVER_PORT = 9092;

async function recordWithDebug() {
  console.log('╔════════════════════════════════════════╗');
  console.log('║   Debug Demo Recorder                 ║');
  console.log('╚════════════════════════════════════════╝');
  console.log('');

  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    recordVideo: {
      dir: outputDir,
      size: { width: 1280, height: 720 }
    }
  });
  const page = await context.newPage();

  // Capture console messages
  page.on('console', msg => console.log('  [browser]', msg.text()));

  try {
    console.log(`🌐 Opening code-server on port ${CODE_SERVER_PORT}...`);
    await page.goto(`http://127.0.0.1:${CODE_SERVER_PORT}/?folder=/home/david/personal/mcp-server-jupyter`, { 
      waitUntil: 'networkidle', 
      timeout: 60000 
    });
    
    console.log('⏳ Waiting 20s for VS Code and extensions to fully load...');
    await page.waitForTimeout(20000);

    // Screenshot 1: Initial state
    await page.screenshot({ path: path.join(outputDir, 'debug-01-initial.png') });
    console.log('📸 Screenshot: Initial state');

    // Try to click the "Yes, I trust" button if visible
    console.log('🔐 Looking for trust button...');
    const trustButtonClicked = await page.evaluate(() => {
      // Look for buttons containing trust text
      const buttons = document.querySelectorAll('button, a.monaco-button');
      for (const btn of buttons) {
        if (btn.textContent && btn.textContent.toLowerCase().includes('trust')) {
          btn.click();
          return true;
        }
      }
      // Also try the specific class
      const trustBtn = document.querySelector('.workspace-trust-editor button');
      if (trustBtn) {
        trustBtn.click();
        return true;
      }
      return false;
    });
    console.log(`  Trust button clicked: ${trustButtonClicked}`);
    
    await page.waitForTimeout(3000);
    
    // Screenshot 2: After trust attempt
    await page.screenshot({ path: path.join(outputDir, 'debug-02-after-trust.png') });
    console.log('📸 Screenshot: After trust attempt');

    // Check what's on page
    const pageTitle = await page.title();
    console.log(`  Page title: ${pageTitle}`);
    
    const bodyText = await page.evaluate(() => document.body.innerText.substring(0, 500));
    console.log(`  Body text preview: ${bodyText.replace(/\n/g, ' ').substring(0, 200)}...`);

    // Try opening file via Ctrl+O instead of Ctrl+P
    console.log('📓 Opening demo.ipynb...');
    await page.keyboard.press('Control+p');
    await page.waitForTimeout(1500);
    
    await page.screenshot({ path: path.join(outputDir, 'debug-03-quickopen.png') });
    console.log('📸 Screenshot: Quick open');
    
    await page.keyboard.type('demo.ipynb', { delay: 80 });
    await page.waitForTimeout(500);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(10000);  // Wait longer for notebook to render

    // Screenshot 4: After opening file
    await page.screenshot({ path: path.join(outputDir, 'debug-04-file-opened.png') });
    console.log('📸 Screenshot: After file open attempt');

    // Check if we can find notebook elements
    const hasNotebook = await page.evaluate(() => {
      return !!document.querySelector('.notebook-editor, .cell, .notebook-cell-list');
    });
    console.log(`  Has notebook elements: ${hasNotebook}`);

    console.log('');
    console.log('✅ Debug recording complete!');
    console.log('  Check the debug-*.png files to see what went wrong');

  } catch (error) {
    console.error('❌ Recording failed:', error.message);
    await page.screenshot({ 
      path: path.join(outputDir, 'debug-error.png'),
      fullPage: true 
    });
    
  } finally {
    await context.close();
    await browser.close();
  }

  console.log('');
  console.log('📁 Debug files:');
  const files = fs.readdirSync(outputDir).filter(f => f.startsWith('debug'));
  files.forEach(f => console.log(`   ${f}`));
}

recordWithDebug().catch(console.error);
