import { defineConfig, devices } from '@playwright/test';

/**
 * Minimal Playwright config for visibility matrix specs (issue #400).
 * Assumes frontend (:3000) and backend (:8000) are already running — no webServer start.
 */
export default defineConfig({
  timeout: 90_000,
  expect: { timeout: 15_000 },
  testDir: '.',
  testMatch: 'visibility_matrix.spec.ts',
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    contextOptions: {
      storageState: {
        cookies: [],
        origins: [
          {
            origin: process.env.BASE_URL || 'http://localhost:3000',
            localStorage: [
              { name: 'copilot-sidebar-visited', value: 'true' },
              { name: 'ucapp.testToken', value: process.env.VITE_TEST_USER_TOKEN || process.env.TEST_USER_TOKEN || '' },
            ],
          },
        ],
      },
    },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
