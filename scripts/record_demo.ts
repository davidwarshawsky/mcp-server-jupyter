/**
 * scripts/record_demo.ts
 * 
 * Hollywood-grade demo recording using Playwright + code-server
 * 
 * Prerequisites:
 *   npm install -g code-server playwright @playwright/test
 *   code-server --bind-addr 127.0.0.1:8080 --auth none .
 * 
 * Usage:
 *   npx ts-node scripts/record_demo.ts
 */

import { chromium, Browser, BrowserContext, Page } from 'playwright';
import * as path from 'path';
import * as fs from 'fs';

interface DemoConfig {
  name: string;
  description: string;
  steps: DemoStep[];
}

interface DemoStep {
  action: 'type' | 'click' | 'wait' | 'execute' | 'screenshot';
  selector?: string;
  text?: string;
  delay?: number;
  timeout?: number;
  filename?: string;
}

// Demo: Auto-EDA Superpower
const autoEdaDemo: DemoConfig = {
  name: 'auto-eda',
  description: 'Autonomous Exploratory Data Analysis in 60 seconds',
  steps: [
    // Open Command Palette
    { action: 'click', selector: 'body' },
    { action: 'wait', timeout: 1000 },
    
    // Type /prompt command
    { action: 'type', text: '/prompt auto-analyst', delay: 80 },
    { action: 'wait', timeout: 2000 },
    
    // Execute cell (Shift+Enter)
    { action: 'execute' },
    { action: 'wait', timeout: 5000 },
    
    // Take final screenshot
    { action: 'screenshot', filename: 'auto-eda-result.png' }
  ]
};

// Demo: Zero-Friction Onboarding (Invisible Setup)
const zeroFrictionDemo: DemoConfig = {
  name: 'zero-friction',
  description: 'First launch experience - no popups, no wizards, just works',
  steps: [
    // Fresh install - just open a notebook
    { action: 'wait', timeout: 2000 },
    
    // Open Command Palette to create new notebook
    { action: 'click', selector: 'body' },
    { action: 'wait', timeout: 500 },
    
    // Wait for silent auto-install toast to appear
    { action: 'wait', timeout: 3000 },
    { action: 'screenshot', filename: 'zero-friction-toast.png' },
    
    // Toast should auto-dismiss, notebook is ready
    { action: 'wait', timeout: 5000 },
    { action: 'screenshot', filename: 'zero-friction-ready.png' }
  ]
};

// Demo: %%duckdb SQL Magic
const duckdbMagicDemo: DemoConfig = {
  name: 'duckdb-magic',
  description: 'Write native SQL with %%duckdb cell magic',
  steps: [
    // Create DataFrame first
    { action: 'type', text: 'import pandas as pd\n', delay: 60 },
    { action: 'type', text: 'sales = pd.DataFrame({\n', delay: 60 },
    { action: 'type', text: '    "region": ["North", "South", "East", "West"],\n', delay: 60 },
    { action: 'type', text: '    "revenue": [10000, 15000, 12000, 18000]\n', delay: 60 },
    { action: 'type', text: '})\n', delay: 60 },
    { action: 'type', text: 'sales', delay: 60 },
    { action: 'execute' },
    { action: 'wait', timeout: 2000 },
    { action: 'screenshot', filename: 'duckdb-magic-dataframe.png' },
    
    // Now use %%duckdb magic - native SQL!
    { action: 'type', text: '%%duckdb\n', delay: 60 },
    { action: 'type', text: 'SELECT region, revenue\n', delay: 60 },
    { action: 'type', text: 'FROM sales\n', delay: 60 },
    { action: 'type', text: 'WHERE revenue > 12000\n', delay: 60 },
    { action: 'type', text: 'ORDER BY revenue DESC', delay: 60 },
    { action: 'execute' },
    { action: 'wait', timeout: 3000 },
    { action: 'screenshot', filename: 'duckdb-magic-result.png' },
    
    // Show %%sql alias too
    { action: 'type', text: '%%sql\n', delay: 60 },
    { action: 'type', text: "SELECT region, SUM(revenue) as total FROM sales GROUP BY region", delay: 60 },
    { action: 'execute' },
    { action: 'wait', timeout: 2000 },
    { action: 'screenshot', filename: 'sql-magic-result.png' }
  ]
};

// Legacy demo for backwards compatibility
const sqlDemo: DemoConfig = {
  name: 'duckdb-sql',
  description: 'Query DataFrames with SQL (legacy function style)',
  steps: [
    // Create DataFrame
    { action: 'type', text: 'import pandas as pd\n', delay: 60 },
    { action: 'type', text: 'df = pd.DataFrame({\n', delay: 60 },
    { action: 'type', text: '    "region": ["North", "South", "East", "West"],\n', delay: 60 },
    { action: 'type', text: '    "revenue": [10000, 15000, 12000, 18000]\n', delay: 60 },
    { action: 'type', text: '})\n', delay: 60 },
    { action: 'execute' },
    { action: 'wait', timeout: 2000 },
    
    // Run SQL query
    { action: 'type', text: '\nquery_dataframes("""\n', delay: 60 },
    { action: 'type', text: '    SELECT region, revenue\n', delay: 60 },
    { action: 'type', text: '    FROM df\n', delay: 60 },
    { action: 'type', text: '    WHERE revenue > 12000\n', delay: 60 },
    { action: 'type', text: '    ORDER BY revenue DESC\n', delay: 60 },
    { action: 'type', text: '""")', delay: 60 },
    { action: 'execute' },
    { action: 'wait', timeout: 3000 },
    
    { action: 'screenshot', filename: 'sql-query-result.png' }
  ]
};

async function recordDemo(config: DemoConfig): Promise<void> {
  console.log(`🎬 Recording demo: ${config.name}`);
  console.log(`   ${config.description}`);
  
  const outputDir = path.join(__dirname, '..', 'docs', 'assets', 'demos');
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const browser: Browser = await chromium.launch({
    headless: true,  // Set to true for CI/CD or WSL
    slowMo: 50  // Slightly slow down for visibility
  });

  const context: BrowserContext = await browser.newContext({
    recordVideo: {
      dir: outputDir,
      size: { width: 1280, height: 720 }
    },
    viewport: { width: 1280, height: 720 }
  });

  const page: Page = await context.newPage();

  try {
    // Navigate to code-server
    console.log('🌐 Opening code-server...');
    await page.goto('http://127.0.0.1:9091');
    await page.waitForLoadState('networkidle');

    // Open demo notebook
    console.log('📓 Opening demo notebook...');
    await page.keyboard.press('Control+P');
    await page.keyboard.type('demo.ipynb');
    await page.keyboard.press('Enter');
    await page.waitForSelector('.notebook-editor', { timeout: 10000 });

    // Execute demo steps
    for (const [index, step] of config.steps.entries()) {
      console.log(`⚡ Step ${index + 1}/${config.steps.length}: ${step.action}`);
      
      switch (step.action) {
        case 'type':
          if (step.text) {
            await page.keyboard.type(step.text, { delay: step.delay || 50 });
          }
          break;

        case 'click':
          if (step.selector) {
            await page.click(step.selector);
          }
          break;

        case 'wait':
          await page.waitForTimeout(step.timeout || 1000);
          break;

        case 'execute':
          await page.keyboard.press('Shift+Enter');
          break;

        case 'screenshot':
          if (step.filename) {
            const screenshotPath = path.join(outputDir, step.filename);
            await page.screenshot({
              path: screenshotPath,
              fullPage: false
            });
            console.log(`📸 Screenshot saved: ${screenshotPath}`);
          }
          break;
      }
    }

    console.log('✅ Demo recording complete!');

  } catch (error) {
    console.error('❌ Demo recording failed:', error);
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }

  // Post-process video to GIF
  const videoPath = path.join(outputDir, `${config.name}.webm`);
  const gifPath = path.join(outputDir, `${config.name}.gif`);
  
  console.log('🎞️  Converting video to GIF...');
  console.log(`   Input: ${videoPath}`);
  console.log(`   Output: ${gifPath}`);
  console.log('');
  console.log('Run this command to convert:');
  console.log(`ffmpeg -i "${videoPath}" -vf "fps=15,scale=1080:-1:flags=lanczos" "${gifPath}"`);
}

// Main execution
async function main() {
  console.log('╔════════════════════════════════════════╗');
  console.log('║   MCP Jupyter Demo Recorder           ║');
  console.log('║   Hollywood-grade automated demos     ║');
  console.log('╚════════════════════════════════════════╝');
  console.log('');
  
  // Check if code-server is running
  console.log('⚠️  Prerequisite: code-server must be running');
  console.log('   Run: VSCODE_IPC_HOOK_CLI= code-server --bind-addr 127.0.0.1:9091 --auth none .');
  console.log('');
  
  const demos = [zeroFrictionDemo, duckdbMagicDemo, autoEdaDemo, sqlDemo];
  
  for (const demo of demos) {
    await recordDemo(demo);
    console.log('');
  }
  
  console.log('🎉 All demos recorded successfully!');
  console.log('');
  console.log('Next steps:');
  console.log('  1. Convert videos to GIFs using ffmpeg commands above');
  console.log('  2. Embed GIFs in documentation:');
  console.log('     ![Auto-EDA Demo](assets/demos/auto-eda.gif)');
}

// Run if executed directly
if (require.main === module) {
  main().catch(console.error);
}
