import { test, expect, _electron as electron } from '@playwright/test';
import { Page, ElectronApplication } from 'playwright';

const APP_PATH = '.vscode-test/vscode-linux-x64-1.85.2/VSCode-linux-x64/code';
const USER_DATA_DIR = '/tmp/vscode-user-data';
const EXTENSION_PATH = process.cwd();

let electronApp: ElectronApplication;
let page: Page;

test.beforeAll(async () => {
  electronApp = await electron.launch({
    executablePath: APP_PATH,
    args: [
      '--no-sandbox',
      '--disable-updates',
      '--skip-welcome',
      '--skip-release-notes',
      '--disable-workspace-trust',
      `--extensionDevelopmentPath=${EXTENSION_PATH}`,
      `--user-data-dir=${USER_DATA_DIR}`,
    ],
  });
  page = await electronApp.firstWindow();
});

test.afterAll(async () => {
  if (electronApp) {
    await electronApp.close();
  }
});

test.describe('VSCode MCP Jupyter E2E', () => {
  test('should run a cell and get output', async () => {
    // Wait for the workbench to be ready
    await page.waitForSelector('.monaco-workbench');

    // Create a new notebook
    await page.keyboard.press('Control+Shift+P');
    await page.locator('input[aria-label="Command Palette"]').type('Jupyter: Create New Blank Notebook');
    await page.locator('a[aria-label="Jupyter: Create New Blank Notebook, command"]').click();

    // Wait for the notebook editor to be visible
    await page.waitForSelector('.notebook-editor');

    // Add code to the first cell
    await page.locator('.cell.code .monaco-editor').first().click();
    await page.keyboard.type('print("Hello from Playwright")');

    // Run the cell
    await page.locator('a[title="Execute Cell"]').first().click();

    // Wait for the output to appear
    await page.waitForSelector('.output_subarea.output_text');

    // Assert on the output
    const output = await page.locator('.output_subarea.output_text').innerText();
    expect(output).toContain('Hello from Playwright');
  });
});
