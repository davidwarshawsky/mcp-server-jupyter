import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for demo recordings.
 * 
 * This config is optimized for recording high-quality demo videos
 * of Jupyter notebooks in a containerized code-server environment.
 * 
 * Usage:
 *   1. Start code-server: docker compose up -d
 *   2. Run tests: npx playwright test --config=playwright.demo.config.ts
 *   3. Videos saved to: ./demo-recordings/
 */
export default defineConfig({
  testDir: './demo-tests',
  
  /* Run tests sequentially for predictable recordings */
  fullyParallel: false,
  workers: 1,
  
  /* Don't retry - we want clean recordings */
  retries: 0,
  
  /* Fail on test.only() */
  forbidOnly: !!process.env.CI,
  
  /* HTML reporter + list for console output */
  reporter: [
    ['html', { outputFolder: '/tmp/demo-recordings/report' }],
    ['list']
  ],
  
  /* Output directory for videos and traces */
  outputDir: '/tmp/demo-recordings/test-results',
  
  /* Global test timeout - demos can be long */
  timeout: 5 * 60 * 1000, // 5 minutes per test
  
  /* Expect timeout for assertions */
  expect: {
    timeout: 30 * 1000, // 30 seconds for expect
  },

  /* Shared settings */
  use: {
    /* Base URL - code-server in Docker */
    baseURL: process.env.CODE_SERVER_URL || 'http://localhost:8443',

    /* Video recording - always on for demos */
    video: {
      mode: 'on',
      size: { width: 1920, height: 1080 },
    },

    /* Viewport - match video size for crisp output */
    viewport: { width: 1920, height: 1080 },

    /* Screenshot on failure */
    screenshot: 'on',

    /* Trace for debugging */
    trace: 'on',

    /* Slow down actions for visibility in demos */
    // Uncomment for slower, more visible demos:
    // launchOptions: {
    //   slowMo: 100,
    // },

    /* Browser context options */
    contextOptions: {
      /* Reduce motion for cleaner recordings */
      reducedMotion: 'no-preference',
    },

    /* Navigation timeout */
    navigationTimeout: 60 * 1000, // 1 minute
    
    /* Action timeout */
    actionTimeout: 30 * 1000, // 30 seconds
  },

  /* Configure browser */
  projects: [
    {
      name: 'chromium-demo',
      use: {
        ...devices['Desktop Chrome'],
        /* Use a larger viewport for demos */
        viewport: { width: 1920, height: 1080 },
        /* Disable headless for local debugging (set via CLI: --headed) */
      },
    },
  ],

  /* Wait for code-server to be ready before running tests */
  webServer: {
    command: 'docker compose up',
    cwd: __dirname,
    url: 'http://localhost:8443',
    reuseExistingServer: true,
    timeout: 120 * 1000, // 2 minutes to start
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
