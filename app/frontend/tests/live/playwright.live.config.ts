import { defineConfig, devices } from '@playwright/test'

// Read-only review of the deployed site, https://advandeb.com — production,
// with real users and research data. Not part of `npm run test:e2e` (whose
// testDir is tests/e2e) nor of vitest (vitest.config.ts excludes tests/live).
//
//   LIVE_EMAIL=… LIVE_PASSWORD=… LIVE_OUT=/some/scratch/dir \
//     npx playwright test -c tests/live/playwright.live.config.ts
//
// LIVE_OUT receives screenshots and evidence; keep it outside the repo.
// Credentials are read from the environment, held in memory and never written
// out. Every spec uses the fixtures in ./guard.ts, which abort any request that
// could change data on the server (see ALWAYS_ALLOWED there).
const OUT = process.env.LIVE_OUT || '/tmp/advandeb-live'

export default defineConfig({
  testDir: '.',
  testMatch: '*.live.ts',
  // One page at a time: polite load, and one shared login whose token pair
  // stays consistent across tests.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 90_000,
  reporter: [['list'], ['json', { outputFile: `${OUT}/report.json` }]],
  outputDir: `${OUT}/test-results`,
  use: {
    baseURL: process.env.LIVE_BASE_URL || 'https://advandeb.com',
    trace: 'off',
    video: 'off',
    screenshot: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    // iPad-like width with Chrome's engine (the installed browser).
    { name: 'tablet', use: { ...devices['Desktop Chrome'], viewport: { width: 768, height: 1024 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 } },
    { name: 'phone', use: { ...devices['Pixel 7'], viewport: { width: 390, height: 844 } } },
  ],
})
