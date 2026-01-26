/**
 * scripts/record_setup_walkthrough.ts
 * 
 * Generates a "One-Click Setup" demo video using Playwright.
 * Records the complete setup wizard flow for documentation and QA.
 * 
 * Prerequisites:
 * 1. npm install -g code-server playwright
 * 2. code-server --bind-addr 127.0.0.1:8080 --auth none .
 * 
 * Usage:
 *   npx ts-node scripts/record_setup_walkthrough.ts
 * 
 * Output:
 *   docs/assets/demos/setup_guide.webm
 */

import { chromium, Browser, BrowserContext, Page } from 'playwright';
import * as path from 'path';
import * as fs from 'fs';

async function recordSetupDemo() {
  const outputDir = path.join(__dirname, '..', 'docs', 'assets', 'demos');
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  console.log('🎥 Starting Setup Walkthrough Recording...');
  
  const browser: Browser = await chromium.launch({
    headless: false, // Must be visible to record
    slowMo: 100      // Slow down actions so users can follow
  });

  // Create context with video recording enabled
  const context: BrowserContext = await browser.newContext({
    recordVideo: {
      dir: outputDir,
      size: { width: 1280, height: 720 }
    },
    viewport: { width: 1280, height: 720 }
  });

  const page: Page = await context.newPage();

  try {
    // 1. Open VS Code (code-server)
    console.log('📺 Opening VS Code...');
    await page.goto('http://127.0.0.1:8080');
    await page.waitForLoadState('networkidle');
    
    // Hide standard notification toasts to clean up the video
    await page.addStyleTag({ 
      content: '.notifications-toasts { display: none !important; }' 
    });

    console.log('⚡ Triggering Quick Start...');

    // 2. Open Command Palette
    await page.keyboard.press('F1');
    await page.waitForTimeout(500);
    await page.keyboard.type('MCP Jupyter: Quick Start');
    await page.waitForTimeout(500);
    await page.keyboard.press('Enter');

    // 3. Select "Automatic Setup" (The One-Click Path)
    // Wait for QuickPick to appear
    const quickPickSelector = '.quick-input-list-entry';
    await page.waitForSelector(quickPickSelector, { timeout: 10000 });
    
    // Find the option containing "Automatic" (our renamed option)
    const automaticOption = page.locator('.quick-input-list-entry')
      .filter({ hasText: /Automatic|Managed/ })
      .first();
    
    await automaticOption.click();
    console.log('✅ Selected Automatic Setup');

    // 4. Wait for installation progress
    console.log('⏳ Waiting for installation...');
    
    // Look for progress notification
    const progressSelector = '.monaco-progress-container';
    try {
      await page.waitForSelector(progressSelector, { timeout: 5000 });
    } catch {
      // Progress might be too fast to catch
    }

    // 5. Wait for Success Notification
    const successSelector = 'text=/MCP Jupyter is ready|ready|Done/i';
    
    // Wait up to 90s for install (includes download time)
    await page.waitForSelector(successSelector, { timeout: 90000 });
    console.log('✅ Installation complete!');
    
    // Hover over the success message to highlight it
    await page.locator(successSelector).first().hover();
    await page.waitForTimeout(2000);

    // 6. Click "Open Example Notebook"
    const exampleButton = page.locator('text=Open Example Notebook');
    if (await exampleButton.isVisible()) {
      await exampleButton.click();
      console.log('📓 Opening example notebook...');
    }
    
    // 7. Wait for notebook to load
    await page.waitForTimeout(3000);

    // 8. Demonstrate "Hello World" (if notebook opened)
    const cellEditor = page.locator('.cell-editor-container').first();
    if (await cellEditor.isVisible()) {
      await cellEditor.click();
      
      // Clear any existing content and type our test
      await page.keyboard.press('Control+a');
      await page.keyboard.type('print("Hello from One-Click Setup!")');
      
      // Execute (Shift+Enter)
      await page.keyboard.press('Shift+Enter');
      console.log('▶️ Executing cell...');
      
      // Wait for output
      try {
        await page.waitForSelector('text=Hello from One-Click Setup!', { timeout: 15000 });
        console.log('✅ Execution verified!');
      } catch {
        console.log('⚠️ Could not verify output (kernel may need time)');
      }
    }
    
    // Linger on success for nice ending
    await page.waitForTimeout(3000);
    console.log('🎬 Recording complete!');

  } catch (error) {
    console.error('❌ Recording failed:', error);
  } finally {
    await context.close(); // Saves the video
    await browser.close();
    
    // Rename the random video file to setup_guide.webm
    const files = fs.readdirSync(outputDir).filter(f => f.endsWith('.webm'));
    
    if (files.length > 0) {
      // Find the newest file (the one we just created)
      const latestVideo = files
        .map(f => ({ 
          name: f, 
          time: fs.statSync(path.join(outputDir, f)).mtime.getTime() 
        }))
        .sort((a, b) => b.time - a.time)[0];
      
      if (latestVideo) {
        const finalPath = path.join(outputDir, 'setup_guide.webm');
        
        // Remove old version if exists
        if (fs.existsSync(finalPath)) {
          fs.unlinkSync(finalPath);
        }
        
        fs.renameSync(path.join(outputDir, latestVideo.name), finalPath);
        console.log(`📹 Video saved to: ${finalPath}`);
        
        // Get file size
        const stats = fs.statSync(finalPath);
        const sizeMB = (stats.size / (1024 * 1024)).toFixed(2);
        console.log(`📊 File size: ${sizeMB} MB`);
        
        // Suggest MP4 conversion
        console.log(`\n💡 To convert to MP4 for web embedding:`);
        console.log(`   ffmpeg -i "${finalPath}" -vf "scale=1280:-2" -c:v libx264 -crf 23 "${path.join(outputDir, 'setup_guide.mp4')}"`);
      }
    } else {
      console.log('⚠️ No video file found - recording may have failed');
    }
  }
}

// Run if called directly
recordSetupDemo().catch(console.error);
