import { test, expect } from '@playwright/test';

test('DuckDB Magic Demo (Robust)', async ({ page }) => {
    // 1. Setup with slower actions for video clarity
    // Reduce motion prevents jerky animations in GIFs
    await page.emulateMedia({ reducedMotion: 'reduce' }); 
    
    console.log('🌐 Opening VS Code...');
    await page.goto('http://localhost:8443/?folder=/config/workspace', { waitUntil: 'networkidle' });

    // 2. Wait for the "Beating Heart" of VS Code (Layout ready)
    await page.waitForSelector('.monaco-workbench');
    
    // 3. FORCE Set the Kernel via Command Palette (The "God Mode" fix)
    // This bypasses the UI picker flakiness entirely
    console.log('🤖 Forcing Kernel Selection...');
    await page.keyboard.press('F1');
    await page.waitForSelector('.quick-input-list');
    await page.keyboard.type('Notebook: Select Notebook Kernel');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(500);
    // Type the name of the kernel we know exists
    await page.keyboard.type('Python 3'); 
    await page.waitForTimeout(500);
    await page.keyboard.press('Enter');

    // 4. Open the file
    console.log('📂 Opening Notebook...');
    await page.keyboard.press('Control+P');
    await page.keyboard.type('demo.ipynb');
    await page.waitForTimeout(500); // Visual pause
    await page.keyboard.press('Enter');

    // 5. Robust Cell Execution Logic
    // Instead of clicking, we use keyboard shortcuts which data scientists actually use
    console.log('▶️ Running Cells...');
    
    // Wait for editor to be active
    await page.waitForSelector('.notebook-editor');

    // Focus first cell
    await page.keyboard.press('Escape'); // Ensure command mode
    await page.keyboard.press('Control+Home'); // Go to top
    
    // Run Cell 1 (Pandas setup)
    await page.keyboard.press('Shift+Enter');
    
    // CRITICAL: Wait for execution to finish before moving on
    // Watch for the "spinner" or "success" icon to stabilize
    await page.waitForSelector('.cell-status-icon.success', { timeout: 10000 });

    // Run Cell 2 (DuckDB Magic)
    // Type it out for effect (The "Movie Magic")
    await page.keyboard.type('%%duckdb');
    await page.keyboard.press('Enter');
    await page.keyboard.type('SELECT region, revenue FROM sales');
    await page.keyboard.press('Shift+Enter');

    // Wait for the result table
    await page.waitForSelector('.output_subarea', { timeout: 5000 });

    // 6. Screenshot for thumbnail
    await page.screenshot({ path: 'demo-recordings/final-state.png' });
});
