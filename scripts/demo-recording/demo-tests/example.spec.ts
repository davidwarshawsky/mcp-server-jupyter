import { test, expect, Page } from '@playwright/test';

/**
 * Example demo recording test.
 * 
 * This demonstrates how to:
 * - Connect to code-server in Docker
 * - Wait for VS Code UI to load
 * - Open a notebook file
 * - Interact with the notebook
 * 
 * The resulting video will be saved to ./demo-recordings/
 */

test.describe('Jupyter Notebook Demo', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to code-server
    await page.goto('/');
    
    // Wait for VS Code to fully load
    // The workbench is the main VS Code container
    await page.waitForSelector('.monaco-workbench', {
      state: 'visible',
      timeout: 60000,
    });
    
    // Wait a bit for extensions to initialize
    await page.waitForTimeout(3000);
  });

  test('open and run notebook cells', async ({ page }) => {
    // Example: Open a notebook file from the explorer
    // Adjust the selector and file path based on your project structure
    
    // Click on Explorer icon in the sidebar
    await page.click('[id="workbench.view.explorer"]');
    
    // Wait for file tree to appear
    await page.waitForSelector('.explorer-viewlet', { timeout: 10000 });
    
    // Optional: Add your notebook interaction logic here
    // For example, opening demo.ipynb:
    // await page.click('text=demo.ipynb');
    
    // Take a screenshot of the current state
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/vscode-loaded.png',
      fullPage: true 
    });
    
    // Keep the page open for a moment at the end of the demo
    await page.waitForTimeout(2000);
  });

  test('demonstrate MCP features', async ({ page }) => {
    // Add your MCP-specific demo steps here
    // This is a placeholder for your actual demo content
    
    // Example: Open command palette
    await page.keyboard.press('Control+Shift+P');
    await page.waitForSelector('.quick-input-widget', { timeout: 5000 });
    
    // Type a command
    await page.keyboard.type('Jupyter: Create New Notebook');
    await page.waitForTimeout(1000);
    
    // Press Enter to execute
    await page.keyboard.press('Enter');
    
    // Wait for notebook to open
    await page.waitForTimeout(3000);
    
    // Screenshot the result
    await page.screenshot({
      path: 'demo-recordings/screenshots/new-notebook.png',
      fullPage: true
    });
  });
});

/**
 * Helper functions for common demo operations
 */

/**
 * Wait for VS Code to be fully ready
 */
async function waitForVSCodeReady(page: Page): Promise<void> {
  // Wait for the workbench
  await page.waitForSelector('.monaco-workbench', { timeout: 60000 });
  
  // Wait for the status bar (indicates VS Code is fully loaded)
  await page.waitForSelector('.statusbar', { timeout: 30000 });
  
  // Wait for any loading indicators to disappear
  await page.waitForFunction(() => {
    const loadingElements = document.querySelectorAll('.loading, .progress-container');
    return loadingElements.length === 0;
  }, { timeout: 30000 });
}

/**
 * Open a file in VS Code via the command palette
 */
async function openFile(page: Page, fileName: string): Promise<void> {
  // Open command palette
  await page.keyboard.press('Control+P');
  await page.waitForSelector('.quick-input-widget', { timeout: 5000 });
  
  // Type the filename
  await page.keyboard.type(fileName);
  await page.waitForTimeout(500);
  
  // Select the file
  await page.keyboard.press('Enter');
  await page.waitForTimeout(1000);
}

/**
 * Run all cells in a Jupyter notebook
 */
async function runAllCells(page: Page): Promise<void> {
  // Open command palette
  await page.keyboard.press('Control+Shift+P');
  await page.waitForSelector('.quick-input-widget', { timeout: 5000 });
  
  // Type the command
  await page.keyboard.type('Notebook: Run All');
  await page.waitForTimeout(500);
  
  // Execute
  await page.keyboard.press('Enter');
}
