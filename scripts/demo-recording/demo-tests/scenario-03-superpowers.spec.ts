import { test, expect } from '@playwright/test';

test.describe('Scenario 3: Superpowers - SQL and Auto-EDA', () => {
    test.beforeEach(async ({ page }) => {
        await page.emulateMedia({ reducedMotion: 'reduce' });
        await page.goto('http://localhost:8443/?folder=/config/workspace', { waitUntil: 'networkidle' });
        await page.waitForSelector('.monaco-workbench', { timeout: 30000 });

        // Close any open editors
        await page.keyboard.press('Control+k');
        await page.keyboard.press('w');

        await page.keyboard.press('Control+p');
        await page.waitForSelector('.quick-input-widget');
        await page.keyboard.type('demo.ipynb');
        await page.keyboard.press('Enter');
        await page.waitForSelector('.notebook-editor');

        // Wait for MCP Ready
        await page.waitForSelector('.notification-toast:has-text("MCP Agent Kernel is ready")', { timeout: 20000 }).catch(() => {});
    });

    test('should demonstrate DuckDB SQL and Auto-EDA', async ({ page }) => {
        // 1. Prepare data in first cell
        console.log('Preparing data...');
        await page.locator('.monaco-list-row.code-cell-row').first().click();
        await page.keyboard.press('Control+a');
        await page.keyboard.press('Backspace');
        await page.keyboard.type("import pandas as pd\nsales_df = pd.DataFrame({'region': ['North', 'South', 'East', 'West'], 'revenue': [100, 150, 120, 180]})");
        await page.keyboard.press('Shift+Enter');
        await page.waitForTimeout(1000);

        // 2. Add and run a DuckDB SQL cell
        console.log('Running DuckDB SQL superpower...');
        await page.keyboard.press('b'); // Add cell below
        await page.keyboard.type("%%duckdb\nSELECT region, revenue * 1.1 as projected_revenue\nFROM sales_df\nWHERE revenue > 110\nORDER BY projected_revenue DESC");
        await page.keyboard.press('Shift+Enter');

        // Wait for table output and verify "right results"
        const table = page.locator('.cell-output-container .rendered-markdown table, .cell-output-container table');
        await expect(table).toBeVisible({ timeout: 15000 });

        // Verify specific data in the output to ensure correctness
        await expect(table).toContainText('South');
        await expect(table).toContainText('West');
        await expect(table).toContainText('165'); // 150 * 1.1
        await expect(table).toContainText('198'); // 180 * 1.1

        await page.screenshot({ path: 'demo-recordings/screenshots/scenario-03-01-duckdb-sql.png' });
        console.log('DuckDB SQL executed successfully with correct results');

        // 3. Run Auto-EDA cell
        console.log('Running Auto-EDA superpower...');
        await page.keyboard.press('b'); // Add cell below
        await page.keyboard.type("/prompt auto-analyst");
        await page.keyboard.press('Shift+Enter');

        // Auto-analyst takes some time as it generates multiple cells/outputs
        console.log('Waiting for Auto-EDA results...');
        await page.waitForTimeout(10000); // Wait for the agent to start doing its thing

        // Look for typical EDA outputs (charts, summaries)
        // Since it's AI generated, we just look for more cells being added or output containers
        await page.screenshot({ path: 'demo-recordings/screenshots/scenario-03-02-auto-eda.png' });

        console.log('Superpowers Scenario Complete');
    });
});
