import { defineConfig, devices } from '@playwright/test'

// A dedicated dev server, not the one on 5173: its /api and /ws proxy points at
// a closed port, so any request a spec does not mock fails instead of reaching
// the backend on :8400, which on this host is production.
const E2E_PORT = 5174
const E2E_URL = `http://127.0.0.1:${E2E_PORT}`

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: E2E_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: `npx vite --host 127.0.0.1 --port ${E2E_PORT} --strictPort`,
    url: E2E_URL,
    // Never attach to a server started some other way: it may proxy to :8400.
    reuseExistingServer: false,
    env: { API_PROXY_TARGET: 'http://127.0.0.1:9' },
  },
})
