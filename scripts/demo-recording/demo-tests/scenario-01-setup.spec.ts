import { test, expect } from '@playwright/test';

test.describe('Scenario 1: Setup and Kernel Selection', () => {
    test.beforeEach(async ({ page }) => {
        await page.emulateMedia({ reducedMotion: 'reduce' });
        console.log('Opening VS Code...');
        await page.goto('http://localhost:8443/?folder=/config/workspace', { waitUntil: 'networkidle' });
        await page.waitForSelector('.monaco-workbench', { timeout: 30000 });

        // Close any open editors (like walkthroughs)
        await page.keyboard.press('Control+k');
        await page.keyboard.press('w');

        console.log('VS Code workbench loaded');
    });

    test('should open notebook and select MCP Agent Kernel', async ({ page }) => {
        // 1. Open the notebook file
        console.log('Opening Notebook demo.ipynb...');
        await page.keyboard.press('Control+p');
        await page.waitForSelector('.quick-input-widget', { timeout: 5000 });
        await page.keyboard.type('demo.ipynb');
        await page.waitForTimeout(1000);
        await page.keyboard.press('Enter');

        // 2. Wait for notebook editor
        console.log('Waiting for notebook editor to appear...');

        // Wait for the selected item in quick open to be what we typed
        const quickOpenItem = page.locator('.quick-input-list-entry.focused:has-text("demo.ipynb")');
        if (await quickOpenItem.isVisible({ timeout: 5000 }).catch(() => false)) {
            console.log('demo.ipynb is focused in quick open');
        } else {
            console.log('demo.ipynb NOT focused, clicking it manually...');
            const item = page.locator('.quick-input-list-entry:has-text("demo.ipynb")').first();
            if (await item.isVisible()) {
                await item.click();
            } else {
                await page.keyboard.press('Enter');
            }
        }

        // Try multiple selectors for notebook editor
        const notebookSelectors = ['.notebook-editor', '.notebookEditor', '.monaco-workbench .notebookOverlay'];
        let found = false;
        for (let i = 0; i < 3; i++) {
            for (const selector of notebookSelectors) {
                try {
                    await page.waitForSelector(selector, { timeout: 5000 });
                    console.log(`Found notebook editor with selector: ${selector}`);
                    found = true;
                    break;
                } catch (e) {}
            }
            if (found) break;
            console.log(`Retry ${i+1} opening notebook...`);
            await page.keyboard.press('Enter');
            await page.waitForTimeout(2000);
        }

        if (!found) {
            console.error('Notebook editor NOT found. Taking diagnostic screenshot...');
            await page.screenshot({ path: 'demo-recordings/screenshots/error-notebook-not-found.png' });
        }

        await page.screenshot({ path: 'demo-recordings/screenshots/scenario-01-01-notebook-opened.png' });

        // 3. Trigger Kernel Selection
        console.log('Checking for kernel selection button...');

        // Use Command Palette to ensure the kernel picker opens reliably
        await page.keyboard.press('F1');
        await page.waitForSelector('.quick-input-widget');
        await page.keyboard.type('Notebook: Select Notebook Kernel');
        await page.waitForTimeout(500);
        await page.keyboard.press('Enter');

        await page.waitForSelector('.quick-input-widget', { timeout: 5000 });
        await page.screenshot({ path: 'demo-recordings/screenshots/scenario-01-02-kernel-picker.png' });

        const mcpKernel = page.locator('.quick-input-list-entry:has-text("MCP Agent Kernel")');
        if (await mcpKernel.isVisible({ timeout: 5000 }).catch(() => false)) {
            await mcpKernel.click();
            console.log('MCP Agent Kernel selected');
        } else {
            console.error('MCP Agent Kernel NOT found in picker!');
            // Log what is available
            const entries = await page.locator('.quick-input-list-entry').allTextContents();
            console.log('Available entries:', entries);

            // Try typing it
            await page.keyboard.type('MCP Agent Kernel');
            await page.waitForTimeout(500);
            await page.keyboard.press('Enter');
        }

        // 4. Verify successful connection notification
        console.log('Waiting for "MCP Agent Kernel is ready!" notification...');
        const notification = page.locator('.notification-toast:has-text("MCP Agent Kernel is ready")');
        await expect(notification).toBeVisible({ timeout: 20000 });

        await page.screenshot({ path: 'demo-recordings/screenshots/scenario-01-03-setup-complete.png' });
        console.log('Setup Scenario Complete');
    });
});
