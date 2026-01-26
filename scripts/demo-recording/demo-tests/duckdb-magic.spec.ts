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
    const editor = page.locator('.notebook-editor, .notebookEditor');
    try {
        await editor.waitFor({ state: 'visible', timeout: 10000 });
        console.log('SUCCESS: Notebook editor found');
    } catch (e) {
        console.error('FAILURE: Notebook editor NOT found.');
        await page.screenshot({ path: 'safe_screenshots/error-no-editor.png' });

        // Diagnostic: What IS visible?
        const textEditor = page.locator('.monaco-editor');
        if (await textEditor.count() > 0 && await textEditor.first().isVisible()) {
            console.log('DIAGNOSTIC: Found .monaco-editor (Text Editor) instead of Notebook!');
            const content = await page.locator('.view-lines').textContent();
            console.log('Text Editor Content Start:', content?.substring(0, 200));
        }

        const welcome = page.locator('text=Welcome');
        if (await welcome.count() > 0 && await welcome.first().isVisible()) {
            console.log('DIAGNOSTIC: Found Welcome Page');
        }

        // Dump some body text to see errors
        const bodyText = await page.textContent('body');
        console.log('DIAGNOSTIC: Body Text Start:', bodyText?.substring(0, 500).replace(/\n/g, ' '));

        // Check notifications
        const notifications = page.locator('.notification-toast');
        if (await notifications.count() > 0) {
            console.log('DIAGNOSTIC: Notifications visible:', await notifications.allInnerTexts());
        }
    }

    await page.screenshot({ path: 'safe_screenshots/debug-04-notebook-state.png' });

    // Debug: Log actual DOM structure for cells
    console.log('DIAGNOSTIC: Looking for cell-like elements...');
    const cellClasses = await page.evaluate(() => {
        // Look for elements that might be cells
        const possibleCells = document.querySelectorAll('[class*="cell"], [class*="Cell"], [class*="code"]');
        const results: string[] = [];
        possibleCells.forEach((el, i) => {
            if (i < 10) { // Limit output
                results.push(`${el.tagName}.${el.className.split(' ').slice(0, 3).join('.')}`);
            }
        });
        return results;
    });
    console.log('Potential cell elements:', cellClasses.join(' | '));

    // 5. Handle kernel selection if needed
    console.log('Checking for kernel selection...');
    const selectKernelBtn = page.locator('text=Select Kernel').first();
    if (await selectKernelBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
        console.log('   Clicking Select Kernel...');
        await selectKernelBtn.click();
        await page.waitForTimeout(2000);
        await page.screenshot({ path: 'safe_screenshots/debug-05-kernel-picker.png' });

        // Look for MCP Agent Kernel first, then fall back to Python
        const mcpKernel = page.locator('.quick-input-list-entry:has-text("MCP Agent Kernel")');
        // Wait a bit for list to populate
        await page.waitForTimeout(1000);

        if (await mcpKernel.isVisible({ timeout: 5000 }).catch(() => false)) {
            console.log('SUCCESS: Found MCP Agent Kernel!');
            await mcpKernel.click();
        } else {
            console.error('FAILURE: MCP Agent Kernel NOT found in picker');
            // List what is found
            const entries = await page.locator('.quick-input-list-entry').allTextContents();
            console.log('Available kernels:', entries.join(', '));

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
                await page.keyboard.press('Enter');
            }
        }
        await page.waitForTimeout(2000);
    } else {
        console.log('Kernel already selected or picker not found');
    }

    await page.screenshot({ path: 'safe_screenshots/debug-06-kernel-selected.png' });
    console.log('Kernel selection complete');

    // 6. Focus and run first cell
    console.log('Running first cell...');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    // Click on a code cell to focus it - try multiple selectors based on VS Code DOM
    const cellSelectors = [
        '.monaco-list-row.code-cell-row',     // VS Code code cell row
        '.monaco-list-row.notebook-cell-row', // Alternative row class
        '.cell-list-container .monaco-list-row', // Any cell in the list
        '.notebook-editor .monaco-editor',    // Editor within notebook
        '.notebookOverlay .monaco-editor',    // Alternative notebook structure
        '.monaco-editor'  // Last resort - any editor
    ];

    let cellFound = false;
    for (const selector of cellSelectors) {
        const cell = page.locator(selector).first();
        if (await cell.isVisible({ timeout: 1000 }).catch(() => false)) {
            console.log(`SUCCESS: Found cell with selector: ${selector}`);
            await cell.click();
            await page.waitForTimeout(500);
            cellFound = true;
            break;
        }
    }

    if (cellFound) {
        // Run the cell
        await page.keyboard.press('Shift+Enter');
        console.log('   Cell executed with Shift+Enter');
    } else {
        console.error('FAILURE: Code cell container NOT found with any selector');
        // Try clicking in the notebook area and running anyway
        console.log('   Attempting keyboard-only execution...');

        // Click anywhere in the notebook editor area first
        const notebookArea = page.locator('.notebook-editor, .notebookOverlay').first();
        if (await notebookArea.isVisible({ timeout: 2000 }).catch(() => false)) {
            await notebookArea.click();
            console.log('   Clicked notebook area');
        }

        await page.keyboard.press('Control+Home');  // Go to top
        await page.waitForTimeout(300);
        await page.keyboard.press('Shift+Enter');
        console.log('   Sent Shift+Enter to run cell');
    }

    // Wait for output
    await page.waitForTimeout(5000);
    await page.screenshot({ path: 'safe_screenshots/debug-07-after-execute.png' });

    console.log('Demo recording complete');
});
