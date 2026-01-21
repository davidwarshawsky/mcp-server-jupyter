/**
 * scripts/record_duckdb_demo.cjs
 * 
 * Records the DuckDB SQL Magic demo with proper kernel selection
 * and cell handling.
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const outputDir = path.join(__dirname, '..', 'docs', 'assets', 'demos');
const CODE_SERVER_PORT = 9092;

async function recordDuckdbDemo() {
  console.log('╔════════════════════════════════════════╗');
  console.log('║   DuckDB SQL Magic Demo Recorder v3   ║');
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

  try {
    console.log(`🌐 Opening code-server on port ${CODE_SERVER_PORT}...`);
    await page.goto(`http://127.0.0.1:${CODE_SERVER_PORT}/?folder=/home/david/personal/mcp-server-jupyter`, { 
      waitUntil: 'networkidle', 
      timeout: 60000 
    });
    
    console.log('⏳ Waiting 15s for VS Code to fully load...');
    await page.waitForTimeout(15000);
    
    // Dismiss any dialogs
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);

    // Open demo notebook using Quick Open
    console.log('📓 Opening demo.ipynb...');
    await page.keyboard.press('Control+p');
    await page.waitForTimeout(1000);
    await page.keyboard.type('demo.ipynb', { delay: 80 });
    await page.waitForTimeout(500);
    await page.keyboard.press('Enter');
    
    // Wait for notebook to open
    console.log('⏳ Waiting 10s for notebook to load...');
    await page.waitForTimeout(10000);

    // Screenshot 1: Notebook opened
    await page.screenshot({ path: path.join(outputDir, 'sql-magic-01-open.png') });
    console.log('📸 Screenshot 1: Notebook opened');

    // Check if kernel needs to be selected - look for "Select Kernel" button
    console.log('🔍 Checking for kernel selection...');
    
    // Try to find and click the kernel status area to trigger kernel selection
    const kernelButton = await page.$('.kernel-action-view-item, [aria-label*="kernel"], [aria-label*="Kernel"]');
    if (kernelButton) {
      console.log('✅ Found kernel button, clicking...');
      await kernelButton.click();
      await page.waitForTimeout(1500);
      
      // Look for Python kernel option in the dropdown
      const pythonOption = await page.$('text=Python 3');
      if (pythonOption) {
        console.log('✅ Selecting Python 3 kernel...');
        await pythonOption.click();
        await page.waitForTimeout(3000);
      }
    }

    // Dismiss any remaining dialogs
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);

    // Now focus on the first code cell
    console.log('🖱️  Focusing on first code cell...');
    
    // Click on the notebook editor area first
    const notebookArea = await page.$('.notebook-editor');
    if (notebookArea) {
      await notebookArea.click();
      await page.waitForTimeout(500);
    }
    
    // Use keyboard to navigate to first cell and enter edit mode
    // Ctrl+Home goes to top, then j/k to navigate cells, Enter to edit
    await page.keyboard.press('Escape');  // Ensure we're in command mode
    await page.waitForTimeout(300);
    await page.keyboard.press('Control+Home');  // Go to top
    await page.waitForTimeout(300);
    
    // Click directly on a code cell's editor
    const codeCell = await page.$('.cell-editor-container .monaco-editor .view-lines');
    if (codeCell) {
      console.log('✅ Found code cell editor, clicking...');
      await codeCell.click();
      await page.waitForTimeout(500);
    } else {
      // Try clicking on any monaco editor within the notebook
      const editor = await page.$('.notebook-cell-list .monaco-editor');
      if (editor) {
        console.log('✅ Found Monaco editor, clicking...');
        await editor.click();
        await page.waitForTimeout(500);
      } else {
        console.log('⚠️  Could not find cell editor, trying keyboard...');
        // Last resort: press Enter to enter edit mode
        await page.keyboard.press('Enter');
        await page.waitForTimeout(500);
      }
    }

    // Clear any existing content
    await page.keyboard.press('Control+a');
    await page.waitForTimeout(200);
    await page.keyboard.press('Backspace');
    await page.waitForTimeout(200);

    // Type Python code line by line with REAL Enter presses
    console.log('⌨️  Typing DataFrame creation code...');
    
    await page.keyboard.type('import pandas as pd', { delay: 35 });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(100);
    
    await page.keyboard.press('Enter');  // Blank line for readability
    await page.waitForTimeout(100);
    
    await page.keyboard.type('sales = pd.DataFrame({', { delay: 35 });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(100);
    
    await page.keyboard.type('    "region": ["North", "South", "East", "West"],', { delay: 35 });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(100);
    
    await page.keyboard.type('    "revenue": [10000, 15000, 12000, 18000]', { delay: 35 });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(100);
    
    await page.keyboard.type('})', { delay: 35 });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(100);
    
    await page.keyboard.type('sales', { delay: 35 });
    
    await page.waitForTimeout(1000);
    
    // Screenshot 2: DataFrame code typed
    await page.screenshot({ path: path.join(outputDir, 'sql-magic-02-dataframe-code.png') });
    console.log('📸 Screenshot 2: DataFrame code typed');

    // Execute cell with Shift+Enter
    console.log('▶️  Executing DataFrame cell (Shift+Enter)...');
    await page.keyboard.press('Shift+Enter');
    
    // Wait and check if kernel selection dialog appears
    await page.waitForTimeout(2000);
    
    // Check for kernel selection dialog
    const selectKernelDialog = await page.$('text=Select Kernel');
    if (selectKernelDialog) {
      console.log('🔧 Kernel selection dialog appeared...');
      
      // Look for Python kernel options
      const pythonEnv = await page.$('text=Python Environments');
      if (pythonEnv) {
        await pythonEnv.click();
        await page.waitForTimeout(1000);
      }
      
      // Select the .venv Python
      const venvPython = await page.$('text=.venv');
      if (venvPython) {
        console.log('✅ Selecting .venv Python kernel...');
        await venvPython.click();
        await page.waitForTimeout(3000);
      } else {
        // Try any Python 3 option
        const anyPython = await page.$('text=/Python 3/');
        if (anyPython) {
          console.log('✅ Selecting Python 3 kernel...');
          await anyPython.click();
          await page.waitForTimeout(3000);
        }
      }
    }
    
    // Wait for execution to complete
    console.log('⏳ Waiting for cell execution...');
    await page.waitForTimeout(5000);

    // Screenshot 3: DataFrame result
    await page.screenshot({ path: path.join(outputDir, 'sql-magic-03-dataframe-result.png') });
    console.log('📸 Screenshot 3: DataFrame result');

    // The Shift+Enter should have moved us to the next cell
    // Make sure we're in edit mode
    await page.waitForTimeout(1000);
    
    // Click on the current cell to ensure we're in edit mode
    const currentCell = await page.$('.notebook-cell.selected .monaco-editor .view-lines');
    if (currentCell) {
      await currentCell.click();
      await page.waitForTimeout(500);
    }

    // Type %%duckdb SQL magic
    console.log('⌨️  Typing %%duckdb SQL query...');
    
    await page.keyboard.type('%%duckdb', { delay: 50 });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(100);
    
    await page.keyboard.type('SELECT region, revenue', { delay: 35 });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(100);
    
    await page.keyboard.type('FROM sales', { delay: 35 });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(100);
    
    await page.keyboard.type('WHERE revenue > 12000', { delay: 35 });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(100);
    
    await page.keyboard.type('ORDER BY revenue DESC', { delay: 35 });

    await page.waitForTimeout(1000);

    // Screenshot 4: SQL code typed
    await page.screenshot({ path: path.join(outputDir, 'sql-magic-04-sql-code.png') });
    console.log('📸 Screenshot 4: SQL code typed');

    // Execute SQL cell
    console.log('▶️  Executing SQL cell...');
    await page.keyboard.press('Shift+Enter');
    await page.waitForTimeout(5000);

    // Screenshot 5: SQL result
    await page.screenshot({ path: path.join(outputDir, 'sql-magic-05-sql-result.png') });
    console.log('📸 Screenshot 5: SQL result');

    console.log('');
    console.log('✅ DuckDB demo recording complete!');

  } catch (error) {
    console.error('❌ Recording failed:', error.message);
    await page.screenshot({ 
      path: path.join(outputDir, 'sql-magic-error.png'),
      fullPage: true 
    });
    
  } finally {
    // Save video path before closing
    const video = page.video();
    
    await context.close();
    await browser.close();
    
    // Rename video file
    if (video) {
      const videoPath = await video.path();
      const newVideoPath = path.join(outputDir, 'sql-magic-demo.webm');
      try {
        fs.renameSync(videoPath, newVideoPath);
        console.log(`🎬 Video saved: ${newVideoPath}`);
        console.log('');
        console.log('To convert to GIF:');
        console.log(`  ffmpeg -i "${newVideoPath}" -vf "fps=12,scale=1080:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" "${path.join(outputDir, 'sql-magic.gif')}" -y`);
      } catch (e) {
        console.log('Video path:', videoPath);
      }
    }
  }

  // List output files
  console.log('');
  console.log('📁 Output files:');
  const files = fs.readdirSync(outputDir).filter(f => f.startsWith('sql-magic'));
  files.forEach(f => console.log(`   ${f} (${Math.round(fs.statSync(path.join(outputDir, f)).size / 1024)}KB)`));
}

recordDuckdbDemo().catch(console.error);
