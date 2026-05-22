import { defineConfig, devices } from '@playwright/test';

// See https://playwright.dev/docs/test-configuration
export default defineConfig({
  timeout: 90_000,
  expect: { timeout: 10_000 },
  testDir: './src/tests',
  globalSetup: './src/tests/global-setup.ts',
  globalTeardown: './src/tests/global-teardown.ts',
  // Skip tests that depend on features not yet wired for CI (mock workspace client)
  testIgnore: process.env.CI ? [
    '**/contract-outputport-mapping*',
    '**/approvals*',
    '**/domain-edit*',
    '**/metadata*',
    '**/roles-approval*',
    '**/semantic-links*',
    '**/cuj-0-setup*',
    '**/cuj-4-glossary*',
    '**/cuj-8-data-products*',
  ] : [],
  retries: process.env.CI ? 1 : 0,
  // Default Playwright CI workers=1 serialized 72 specs and hit the 20-min job
  // timeout. Bump to 2 in CI; the existing retries: 1 covers any flake from
  // workers contending on the shared Postgres service.
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? 'html' : 'list',
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    video: 'retain-on-failure',
    // Dismiss the Ask Ontos copilot side-panel that opens by default for
    // first-time visitors. Without this, the z-50 fixed panel intercepts
    // pointer events on the main content area and causes click timeouts.
    contextOptions: {
      storageState: {
        cookies: [],
        origins: [{
          origin: process.env.BASE_URL || 'http://localhost:3000',
          localStorage: [{ name: 'copilot-sidebar-visited', value: 'true' }],
        }],
      },
    },
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'yarn dev:frontend --port 3000',
    url: 'http://localhost:3000',
    reuseExistingServer: true,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});


