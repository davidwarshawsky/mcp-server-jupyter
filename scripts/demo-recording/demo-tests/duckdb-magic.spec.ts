import { test, expect, Page } from '@playwright/test';

/**
 * DuckDB SQL Magic Demo Recording
 * 
 * Records a demo of:
 * 1. Opening a Jupyter notebook in code-server
 * 2. Selecting a Python kernel  
 * 3. Running a cell that creates a pandas DataFrame
 * 4. Running a cell with %%duckdb SQL magic
 */

test.describe('DuckDB SQL Magic Demo', () => {
  test('show duckdb magic workflow', async ({ page }) => {
    // Set a longer timeout for the whole test
    test.setTimeout(180000);
    
    console.log('Step 1: Navigate to code-server with folder parameter');
    await page.goto('http://localhost:8443/?folder=/config/workspace', {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    
    // Wait for VS Code workbench to fully load
    console.log('Step 2: Waiting for VS Code workbench...');
    await page.waitForSelector('.monaco-workbench', {
      state: 'visible',
      timeout: 90000,
    });
    
    // Wait for activity bar (left sidebar with icons)
    console.log('Step 2b: Waiting for activity bar...');
    await page.waitForSelector('.activitybar', { 
      state: 'visible',
      timeout: 30000 
    });
    
    // Extra wait for extensions to fully initialize
    console.log('Step 3: Waiting for extensions to initialize...');
    await page.waitForTimeout(10000);
    
    // Close Welcome tab if it exists
    console.log('Step 3b: Closing Welcome tab if present...');
    try {
      const welcomeTabClose = page.locator('.tab:has-text("Welcome") .codicon-close, .tab:has-text("Get Started") .codicon-close');
      if (await welcomeTabClose.isVisible({ timeout: 3000 })) {
        await welcomeTabClose.click();
        console.log('   Closed Welcome tab');
        await page.waitForTimeout(1000);
      }
    } catch (e) {
      console.log('   No Welcome tab found (good!)');
    }
    
    // Take initial screenshot
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/01-vscode-loaded.png',
      fullPage: true 
    });
    
    // Open the notebook file using the command palette (most reliable method)
    console.log('Step 4: Opening demo.ipynb via command palette...');
    await page.keyboard.press('Control+P'); // Quick Open
    await page.waitForSelector('.quick-input-widget', { timeout: 5000 });
    await page.waitForTimeout(500);
    await page.keyboard.type('demo.ipynb');
    
    // Wait for the file to appear in the quick open list
    await page.waitForSelector('.quick-input-list-entry:has-text("demo.ipynb")', { timeout: 10000 });
    console.log('   Found demo.ipynb in Quick Open list');
    
    await page.waitForTimeout(1000);
    await page.keyboard.press('Enter');
    
    // Give it some time to start opening
    await page.waitForTimeout(3000);
    
    // Screenshot to see what happened after pressing Enter
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/01b-after-quickopen-enter.png',
      fullPage: true 
    });
    
    // Wait for the notebook to open and the first cell to be rendered
    console.log('Step 5: Waiting for notebook editor to be ready...');
    
    // Try multiple selectors for notebook detection
    try {
      await page.waitForSelector('.notebook-cell-list, .monaco-workbench .part.editor .notebook-editor', { 
        state: 'visible',
        timeout: 30000 
      });
      console.log('   Notebook editor is ready (found via notebook selectors)');
    } catch (e) {
      // Take debug screenshot
      await page.screenshot({ 
        path: 'demo-recordings/screenshots/01c-notebook-wait-failed.png',
        fullPage: true 
      });
      console.log('   Notebook not detected, taking screenshot for debug');
    }
    
    await page.waitForTimeout(5000);
    
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/02-notebook-opened.png',
      fullPage: true 
    });
    
    // Dismiss any extension recommendation dialogs
    console.log('Step 5b: Dismissing any extension dialogs...');
    try {
      const dontShowAgain = page.locator('text=Don\'t Show Again');
      if (await dontShowAgain.isVisible({ timeout: 2000 })) {
        await dontShowAgain.click();
        console.log('   Dismissed extension recommendation dialog.');
      }
    } catch (e) {
      // No dialog, continue
    }
    
    // Handle kernel selection - the kernel selector is in the TOP-RIGHT of the notebook
    console.log('Step 6: Handling kernel selection - selecting MCP Agent Kernel...');
    
    // Take a screenshot to see current state
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/02b-kernel-dialog-state.png',
      fullPage: true 
    });
    
    // The kernel selector shows "Select Kernel" in the notebook toolbar (top-right)
    // We want to select "🤖 MCP Agent Kernel" - our custom kernel
    
    try {
      // Look for the "Select Kernel" button in the notebook toolbar
      // Use .first() because there may be multiple (one per code cell)
      const selectKernelBtn = page.locator('text=Select Kernel').first();
      
      if (await selectKernelBtn.isVisible({ timeout: 5000 })) {
        console.log('   Found "Select Kernel" button - clicking it.');
        await selectKernelBtn.click();
        await page.waitForTimeout(2000);
        
        // Take screenshot of the dropdown
        await page.screenshot({ 
          path: 'demo-recordings/screenshots/02c-kernel-dropdown.png',
          fullPage: true 
        });
        
        // First, look for our MCP Agent Kernel directly
        const mcpKernel = page.locator('.quick-input-list-entry:has-text("MCP Agent Kernel"), .quick-input-list-entry:has-text("🤖")');
        if (await mcpKernel.isVisible({ timeout: 3000 })) {
          console.log('   Found MCP Agent Kernel - clicking it!');
          await mcpKernel.first().click();
          await page.waitForTimeout(3000);
        } else {
          // Check if we need to install/enable extensions first
          const installExtensions = page.locator('text=Install/Enable suggested extensions');
          if (await installExtensions.isVisible({ timeout: 2000 })) {
            console.log('   Found "Install/Enable suggested extensions" - clicking it.');
            await installExtensions.click();
            
            // Wait for extensions to be enabled
            console.log('   Waiting for extensions to be enabled...');
            await page.waitForTimeout(10000);
            
            // Now click Select Kernel again and look for MCP
            if (await selectKernelBtn.isVisible({ timeout: 5000 })) {
              await selectKernelBtn.click();
              await page.waitForTimeout(2000);
              
              if (await mcpKernel.isVisible({ timeout: 3000 })) {
                console.log('   Found MCP Agent Kernel after enabling - clicking it!');
                await mcpKernel.first().click();
                await page.waitForTimeout(3000);
              }
            }
          } else {
            // Fallback: Look for Jupyter Kernels category
            const jupyterKernels = page.locator('.quick-input-list-entry:has-text("Jupyter Kernels")');
            if (await jupyterKernels.isVisible({ timeout: 2000 })) {
              console.log('   Clicking Jupyter Kernels category...');
              await jupyterKernels.click();
              await page.waitForTimeout(2000);
              
              // Now look for MCP Agent Kernel
              if (await mcpKernel.isVisible({ timeout: 3000 })) {
                console.log('   Found MCP Agent Kernel in Jupyter Kernels!');
                await mcpKernel.first().click();
                await page.waitForTimeout(3000);
              } else {
                // Type to filter
                console.log('   Typing "MCP" to filter...');
                await page.keyboard.type('MCP');
                await page.waitForTimeout(1000);
                await page.keyboard.press('Enter');
                await page.waitForTimeout(3000);
              }
            } else {
              // Type to filter
              console.log('   Typing "MCP" to filter for MCP Agent Kernel...');
              await page.keyboard.type('MCP');
              await page.waitForTimeout(1000);
              await page.keyboard.press('Enter');
              await page.waitForTimeout(3000);
            }
          }
        }
      } else {
        console.log('   No Select Kernel button visible - kernel may already be selected.');
      }
      
    } catch (e) {
      console.log('   Kernel selection error:', e);
    }
    
    console.log('   Kernel selection completed.');
    
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/03-kernel-selected.png',
      fullPage: true 
    });
    
    // Find and click on the first CODE cell (skip markdown cells)
    console.log('Step 7: Focusing first CODE cell (skipping markdown)...');
    
    try {
      // Target specifically CODE cells, not markdown cells
      // .code-cell-row is the VS Code class for code cells in notebooks
      const firstCodeCell = page.locator('.notebook-editor .code-cell-row .monaco-editor').first();
      await firstCodeCell.scrollIntoViewIfNeeded();
      await firstCodeCell.click({ timeout: 30000 });
      console.log('   Clicked on the first CODE cell editor.');
    } catch (e) {
      console.log('   Could not click code cell editor, trying keyboard navigation as fallback.');
      // Press Escape to ensure we're in command mode, then navigate
      await page.keyboard.press('Escape');
      await page.waitForTimeout(300);
      // Press 'j' twice to skip markdown cell and get to first code cell
      await page.keyboard.press('j');
      await page.waitForTimeout(200);
      await page.keyboard.press('j');
      await page.waitForTimeout(200);
      await page.keyboard.press('Enter'); // Enter edit mode
    }
    
    await page.waitForTimeout(1000);
    
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/04-cell-focused.png',
      fullPage: true 
    });
    
    // Run the first cell (should be the pandas DataFrame cell)
    console.log('Step 8: Running first code cell with Shift+Enter...');
    
    // Use Shift+Enter to run the cell AND move to the next cell
    await page.keyboard.press('Shift+Enter');
    
    // This may trigger the kernel selection dialog - handle it
    console.log('   Checking if kernel selection dialog appeared...');
    await page.waitForTimeout(2000);
    
    // Handle kernel source selection if it appears
    // The dialog shows: "Type to choose a kernel source"
    // Options are: "Python Environments", "Jupyter Kernels", etc.
    try {
      const quickInput = page.locator('.quick-input-widget:visible');
      if (await quickInput.isVisible({ timeout: 3000 })) {
        console.log('   Kernel selection dialog appeared!');
        
        // Take screenshot of the dialog
        await page.screenshot({ 
          path: 'demo-recordings/screenshots/05a-kernel-dialog.png',
          fullPage: true 
        });
        
        // Check if this is asking for kernel SOURCE (first level)
        const typeToChoose = await page.locator('text=Type to choose a kernel source').isVisible({ timeout: 1000 }).catch(() => false);
        const jupyterKernels = page.locator('.quick-input-list-entry:has-text("Jupyter Kernels")');
        const pythonEnvs = page.locator('.quick-input-list-entry:has-text("Python Environments")');
        
        if (await jupyterKernels.isVisible({ timeout: 2000 })) {
          // Best option: Jupyter Kernels (uses ipykernel)
          console.log('   Found "Jupyter Kernels" - clicking it...');
          await jupyterKernels.click();
          await page.waitForTimeout(2000);
          
          // Now select the Python 3 kernel from the list
          const python3Kernel = page.locator('.quick-input-list-entry:has-text("Python 3"), .quick-input-list-entry:has-text("python3")');
          if (await python3Kernel.isVisible({ timeout: 3000 })) {
            console.log('   Clicking Python 3 kernel...');
            await python3Kernel.first().click();
            await page.waitForTimeout(3000);
          } else {
            // Press Enter to select first option
            console.log('   No Python 3 found, pressing Enter for first option...');
            await page.keyboard.press('Enter');
            await page.waitForTimeout(2000);
          }
        } else if (await pythonEnvs.isVisible({ timeout: 2000 })) {
          // Fallback: Python Environments
          console.log('   Found "Python Environments" - clicking it...');
          await pythonEnvs.click();
          await page.waitForTimeout(2000);
          
          // Now select Python 3 from the list
          const python3 = page.locator('.quick-input-list-entry:has-text("Python 3"), .quick-input-list-entry:has-text("/usr/bin/python")');
          if (await python3.isVisible({ timeout: 3000 })) {
            console.log('   Clicking Python 3...');
            await python3.first().click();
            await page.waitForTimeout(3000);
          } else {
            console.log('   No Python 3 found, pressing Enter...');
            await page.keyboard.press('Enter');
            await page.waitForTimeout(2000);
          }
        } else {
          // Maybe dialog is showing kernels directly (not sources)
          const anyPython = page.locator('.quick-input-list-entry:has-text("Python"), .quick-input-list-entry:has-text("python")');
          if (await anyPython.isVisible({ timeout: 2000 })) {
            console.log('   Found Python kernel option - clicking it...');
            await anyPython.first().click();
            await page.waitForTimeout(3000);
          } else {
            // Last resort: type "python" to filter and press Enter
            console.log('   Typing "python" to filter kernels...');
            await page.keyboard.type('python');
            await page.waitForTimeout(1000);
            await page.keyboard.press('Enter');
            await page.waitForTimeout(3000);
          }
        }
        
        // Screenshot after kernel selection
        await page.screenshot({ 
          path: 'demo-recordings/screenshots/05b-kernel-selected.png',
          fullPage: true 
        });
        
        // The cell may need to be run again after kernel connects
        console.log('   Waiting for kernel to connect...');
        await page.waitForTimeout(5000);
        
        // Check if we need to re-run the cell (kernel just connected)
        // Look for the cell execution indicator or run the cell again
        const hasOutput = await page.locator('.notebook-editor .output-element').isVisible({ timeout: 2000 }).catch(() => false);
        if (!hasOutput) {
          console.log('   No output yet, re-running cell...');
          // Make sure we're focused on the first code cell
          const firstCodeCell = page.locator('.notebook-editor .code-cell-row .monaco-editor').first();
          await firstCodeCell.click({ timeout: 5000 }).catch(() => {});
          await page.keyboard.press('Shift+Enter');
          await page.waitForTimeout(3000);
        }
      }
    } catch (e) {
      console.log('   Kernel dialog handling error:', e);
    }
    
    // Wait for execution - look for output to appear
    console.log('   Waiting for cell output...');
    try {
      await page.waitForSelector('.notebook-editor .output-element', { timeout: 20000 });
      console.log('   Cell output detected!');
    } catch (e) {
      console.log('   No output detected yet, waiting more...');
    }
    await page.waitForTimeout(3000);
    
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/05-first-cell-executed.png',
      fullPage: true 
    });
    
    // Move to the next cell (SQL cell)
    console.log('Step 9: Moving to SQL cell...');
    
    // After Shift+Enter, we should already be on the next cell
    // But let's make sure we're on the second CODE cell
    try {
      const secondCodeCell = page.locator('.notebook-editor .code-cell-row .monaco-editor').nth(1);
      await secondCodeCell.scrollIntoViewIfNeeded();
      await secondCodeCell.click({ timeout: 10000 });
      console.log('   Clicked on second CODE cell');
    } catch (e) {
      console.log('   Could not click second cell, cursor should already be there');
    }
    
    await page.waitForTimeout(1000);
    
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/06-sql-cell-focused.png',
      fullPage: true 
    });
    
    // Run the SQL cell
    console.log('Step 10: Running SQL cell with Shift+Enter...');
    await page.keyboard.press('Shift+Enter');
    
    // Wait for SQL execution - look for second output
    console.log('   Waiting for SQL output...');
    try {
      // Wait for at least 2 output elements (one from each code cell)
      await page.waitForFunction(() => {
        const outputs = document.querySelectorAll('.notebook-editor .output-element');
        return outputs.length >= 2;
      }, { timeout: 15000 });
      console.log('   SQL output detected!');
    } catch (e) {
      console.log('   SQL output not detected, continuing...');
    }
    await page.waitForTimeout(3000);
    
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/07-sql-executed.png',
      fullPage: true 
    });
    
    // Final pause to show results
    console.log('Step 11: Showing final results...');
    await page.waitForTimeout(3000);
    
    await page.screenshot({ 
      path: 'demo-recordings/screenshots/08-final.png',
      fullPage: true 
    });
    
    console.log('Demo recording complete!');
  });
});
