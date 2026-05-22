import { APIRequestContext, Page } from '@playwright/test'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

// Per-worker memo so a spec that survives a worker restart doesn't pay the
// API-probe cost twice. Cross-worker dedup is handled by global-setup.ts.
let presentInThisWorker = false

async function isDemoDataPresent(request: APIRequestContext): Promise<boolean> {
  if (presentInThisWorker) return true
  try {
    const resp = await request.get(`${BACKEND_URL}/api/data-products`, {
      timeout: 10_000,
    })
    if (!resp.ok()) return false
    const products = await resp.json()
    const ok = Array.isArray(products) && products.length > 0
    if (ok) presentInThisWorker = true
    return ok
  } catch {
    return false
  }
}

/**
 * Ensure demo data exists. Loads if absent; no-ops if global-setup or a prior
 * spec already populated the DB. Specs can keep their existing
 * `test.beforeAll(loadDemoData)` hooks — they're cheap after the first call.
 */
export async function loadDemoData(request: APIRequestContext) {
  if (await isDemoDataPresent(request)) return { skipped: true }

  const resp = await request.post(`${BACKEND_URL}/api/settings/demo-data/load`)
  if (!resp.ok()) {
    const body = await resp.text()
    throw new Error(`Failed to load demo data (${resp.status()}): ${body}`)
  }
  presentInThisWorker = true
  return resp.json()
}

/**
 * No-op by design. End-of-run cleanup is owned by global-teardown.ts so
 * specs don't repeatedly drop+reload the shared demo dataset between files.
 * Kept exported so existing `test.afterAll(clearDemoData)` hooks compile;
 * if a spec genuinely needs to clear mid-run, call the DELETE endpoint
 * directly via the APIRequestContext.
 */
export async function clearDemoData(_request: APIRequestContext) {
  return { skipped: true }
}

/**
 * Dismiss the copilot side-panel that opens by default for first-time visitors.
 * Playwright starts with clean localStorage, so the panel always appears and
 * intercepts clicks on the main content area. Setting the visited key prevents it.
 * Must be called before `page.goto()` in each test, or once in beforeEach.
 */
export async function dismissCopilot(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('copilot-sidebar-visited', 'true')
  })
}
