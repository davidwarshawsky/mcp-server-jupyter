const { chromium } = require('playwright');

async function inspectNotebook() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();

  console.log('Opening code-server...');
  await page.goto('http://127.0.0.1:9092/?folder=/home/david/personal/mcp-server-jupyter', { 
    waitUntil: 'networkidle', 
    timeout: 60000 
  });
  
  console.log('Waiting 20s for VS Code to load...');
  await page.waitForTimeout(20000);

  // Open notebook
  console.log('Opening demo.ipynb...');
  await page.keyboard.press('Control+p');
  await page.waitForTimeout(1500);
  await page.keyboard.type('demo.ipynb', { delay: 80 });
  await page.waitForTimeout(500);
  await page.keyboard.press('Enter');
  await page.waitForTimeout(15000);

  // Inspect the DOM
  console.log('\n=== Inspecting notebook DOM ===\n');
  
  const notebookInfo = await page.evaluate(() => {
    const info = {};
    
    // Check for notebook container
    const notebook = document.querySelector('.notebook-editor');
    info.hasNotebookEditor = !!notebook;
    
    // Check for cells
    const cells = document.querySelectorAll('.cell, .notebook-cell, .code-cell-row');
    info.cellCount = cells.length;
    info.cellClasses = [...new Set([...document.querySelectorAll('[class*="cell"]')].map(e => e.className.split(' ').filter(c => c.includes('cell')).join(' ')))].slice(0, 10);
    
    // Check for Monaco editors in notebook
    const monacoEditors = document.querySelectorAll('.monaco-editor');
    info.monacoEditorCount = monacoEditors.length;
    
    // Check for input areas
    const inputAreas = document.querySelectorAll('.cell-editor-container, .input-cell, .cell-input-area');
    info.inputAreaCount = inputAreas.length;
    
    // Check active element
    info.activeElement = document.activeElement?.tagName + '.' + document.activeElement?.className?.split(' ').slice(0, 3).join('.');
    
    // Get visible text in main content area
    const mainContent = document.querySelector('.editor-container, .split-view-container');
    info.mainContentPreview = mainContent?.innerText?.substring(0, 300) || 'No main content found';
    
    // Check for any visible dialogs/overlays
    const overlays = document.querySelectorAll('.monaco-dialog-box, .quick-input-widget, .suggest-widget');
    info.visibleOverlays = overlays.length;
    
    // Get classes of notebook-related elements
    info.notebookClasses = [...document.querySelectorAll('[class*="notebook"]')].map(e => e.className).slice(0, 10);
    
    return info;
  });
  
  console.log('Notebook info:', JSON.stringify(notebookInfo, null, 2));
  
  // Take screenshot
  await page.screenshot({ path: '/home/david/personal/mcp-server-jupyter/docs/assets/demos/inspect-notebook.png' });
  console.log('\nScreenshot saved to inspect-notebook.png');
  
  await context.close();
  await browser.close();
}

inspectNotebook().catch(console.error);
