import { defineConfig, devices } from '@playwright/test';

// See https://playwright.dev/docs/test-configuration
export default defineConfig({
  // 60s is comfortably above the slowest healthy test (~a few s); the old 90s
  // mainly prolonged hung/broken tests (90s x retries) and slowed CI.
  timeout: 60_000,
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
  // CI shards the suite across runners (see e2e-tests matrix). Each shard emits
  // a 'blob' report; a merge-reports job stitches them into one HTML report.
  // Locally, 'list' for readable streaming output.
  reporter: process.env.CI ? 'blob' : 'list',
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    video: 'retain-on-failure',
    // Demo mode: slow each browser action so a human can follow the run.
    // Gated on DEMO so normal/CI runs are unaffected. Override the pause with
    // DEMO_SLOWMO (ms), e.g. DEMO_SLOWMO=1500 yarn demo.
    launchOptions: {
      slowMo: process.env.DEMO ? Number(process.env.DEMO_SLOWMO) || 800 : 0,
    },
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
  webServer: [
    {
      command: 'yarn dev:frontend --port 3000',
      url: 'http://localhost:3000',
      reuseExistingServer: true,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    // Demo mode also brings up the backend so `yarn demo` is a single command.
    // reuseExistingServer means an already-running backend is reused, never
    // restarted. Omitted entirely outside demo mode (CI/normal runs manage the
    // backend themselves).
    ...(process.env.DEMO ? [{
      // MOCK_WORKSPACE_CLIENT=true returns a mock Databricks client instantly
      // instead of calling the workspace, so the demo runs fully locally with
      // no Databricks connectivity (the core journeys don't need a live client).
      command: 'MOCK_WORKSPACE_CLIENT=true hatch -e dev run dev-backend',
      cwd: '..',
      url: 'http://localhost:8000/api/health',
      reuseExistingServer: true,
      timeout: 120_000,
      stdout: 'pipe' as const,
      stderr: 'pipe' as const,
    }] : []),
  ],
});


