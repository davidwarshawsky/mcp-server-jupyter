import { test, expect } from '@playwright/test';

test('DuckDB Magic Demo (Robust)', async ({ page }) => {
    // 1. Setup with slower actions for video clarity
    await page.emulateMedia({ reducedMotion: 'reduce' }); 
    
    console.log('Opening VS Code...');
    await page.goto('http://localhost:8443/?folder=/config/workspace', { waitUntil: 'networkidle' });
    
    // 2. Wait for VS Code to be ready
    await page.waitForSelector('.monaco-workbench', { timeout: 30000 });
    console.log('VS Code workbench loaded');
    
    // Wait a bit for extensions to initialize
    await page.waitForTimeout(5000);
    
    // Take debug screenshot
    await page.screenshot({ path: 'demo-recordings/screenshots/debug-01-vscode-ready.png' });

    // 3. Open the notebook file first
    console.log('Opening Notebook...');
    await page.keyboard.press('Control+p');
    await page.waitForSelector('.quick-input-widget', { timeout: 5000 });
    await page.keyboard.type('demo.ipynb');
    await page.waitForTimeout(1000);
    await page.keyboard.press('Enter');
    
    // Wait for notebook to start loading
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'demo-recordings/screenshots/debug-02-after-open.png' });
    
    // 4. Wait for notebook editor - try multiple selectors
    console.log('Waiting for notebook editor...');
    try {
        await page.waitForSelector('.notebook-editor, .notebookEditor', { timeout: 30000 });
        console.log('Notebook editor found');
    } catch (e) {
        console.log('Notebook editor not found with standard selectors');
        await page.screenshot({ path: 'demo-recordings/screenshots/debug-03-notebook-not-found.png' });
    }
    
    await page.screenshot({ path: 'demo-recordings/screenshots/debug-04-notebook-state.png' });
    
    // 5. Handle kernel selection if needed
    console.log('Checking for kernel selection...');
    const selectKernelBtn = page.locator('text=Select Kernel').first();
    if (await selectKernelBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        console.log('   Clicking Select Kernel...');
        await selectKernelBtn.click();
        await page.waitForTimeout(2000);
        await page.screenshot({ path: 'demo-recordings/screenshots/debug-05-kernel-picker.png' });
        
        // Look for MCP Agent Kernel first, then fall back to Python
        const mcpKernel = page.locator('.quick-input-list-entry:has-text("MCP Agent Kernel")');
        if (await mcpKernel.isVisible({ timeout: 2000 }).catch(() => false)) {
            console.log('   Found MCP Agent Kernel!');
            await mcpKernel.click();
        } else {
            // Fall back to Python
            console.log('   Looking for Python kernel...');
            const pythonEnvs = page.locator('.quick-input-list-entry:has-text("Python Environments")');
            if (await pythonEnvs.isVisible({ timeout: 2000 }).catch(() => false)) {
                await pythonEnvs.click();
                await page.waitForTimeout(1000);
            }
            const python3 = page.locator('.quick-input-list-entry:has-text("Python 3")').first();
            if (await python3.isVisible({ timeout: 3000 }).catch(() => false)) {
                await python3.click();
            } else {
                // Just press Enter to select first option
                await page.keyboard.press('Enter');
            }
        }
        await page.waitForTimeout(2000);
    }
    
    await page.screenshot({ path: 'demo-recordings/screenshots/debug-06-kernel-selected.png' });
    console.log('Kernel selection complete');
    
    // 6. Focus and run first cell
    console.log('Running first cell...');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    
    // Click on a code cell to focus it
    const codeCell = page.locator('.cell-editor-container').first();
    if (await codeCell.isVisible({ timeout: 3000 }).catch(() => false)) {
        await codeCell.click();
        await page.waitForTimeout(500);
    }
    
    // Run the cell
    await page.keyboard.press('Shift+Enter');
    console.log('   Cell executed with Shift+Enter');
    
    // Wait for output
    await page.waitForTimeout(5000);
    await page.screenshot({ path: 'demo-recordings/screenshots/debug-07-after-execute.png' });
    
    console.log('Demo recording complete');
});
