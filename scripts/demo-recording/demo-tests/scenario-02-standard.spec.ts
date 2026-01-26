import { test, expect } from '@playwright/test';

test.describe('Scenario 2: Standard Features - Variable Dashboard', () => {
    test.beforeEach(async ({ page }) => {
        await page.emulateMedia({ reducedMotion: 'reduce' });
        console.log('Opening VS Code...');
        await page.goto('http://localhost:8443/?folder=/config/workspace', { waitUntil: 'networkidle' });
        await page.waitForSelector('.monaco-workbench', { timeout: 30000 });

        // Close any open editors
        await page.keyboard.press('Control+k');
        await page.keyboard.press('w');

        // Open notebook and ensure kernel is selected (simple version for this test)
        await page.keyboard.press('Control+p');
        await page.waitForSelector('.quick-input-widget');
        await page.keyboard.type('demo.ipynb');
        await page.keyboard.press('Enter');
        await page.waitForSelector('.notebook-editor');

        // Wait for MCP Ready notification to be sure kernel is set
        await page.waitForSelector('.notification-toast:has-text("MCP Agent Kernel is ready")', { timeout: 20000 }).catch(() => {
            console.log('Ready notification not found, assuming already connected');
        });
    });

    test('should run python cell and show variables in dashboard', async ({ page }) => {
        // 1. Focus first cell and run it
        console.log('Executing first cell...');
        await page.locator('.monaco-list-row.code-cell-row').first().click();

        // Replace cell content with a simple dataframe
        await page.keyboard.press('Control+a');
        await page.keyboard.press('Backspace');
        await page.keyboard.type("import pandas as pd\ndf = pd.DataFrame({'a': [1, 2, 3], 'b': ['high', 'medium', 'low']})\ndf");
        await page.keyboard.press('Shift+Enter');

        // 2. Wait for execution to finish (output appears)
        await page.waitForSelector('.cell-output-container', { timeout: 10000 });
        await page.screenshot({ path: 'demo-recordings/screenshots/scenario-02-01-cell-executed.png' });

        // 3. Open MCP Variables View
        console.log('Opening MCP Variables view...');
        // Try clicking the activity bar icon if we can find it, otherwise use command palette
        await page.keyboard.press('F1');
        await page.waitForSelector('.quick-input-widget');
        await page.keyboard.type('View: Show MCP Jupyter');
        await page.keyboard.press('Enter');

        // Wait for the view to be visible
        await page.waitForSelector('.pane-header:has-text("Agent Context")', { timeout: 5000 });

        // 4. Verify variable 'df' is present and has correct type
        console.log('Verifying variable in dashboard...');
        const variableItem = page.locator('.monaco-list-row:has-text("df")');
        await expect(variableItem).toBeVisible({ timeout: 10000 });

        // Check for specific text that indicates it's a DataFrame (usually shown in the value or type column)
        await expect(variableItem).toContainText('DataFrame');

        await page.screenshot({ path: 'demo-recordings/screenshots/scenario-02-02-variable-dashboard.png' });
        console.log('Standard Features Scenario Complete');
    });
});
