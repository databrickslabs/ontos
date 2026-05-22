import { request, FullConfig } from '@playwright/test'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

/**
 * Load demo data once before the entire Playwright run.
 *
 * Previously every spec ran loadDemoData in its own beforeAll, which meant
 * ~9 full SQL replays per run against a shared backend. With workers=2 this
 * is the dominant cost — most of the 20-minute job timeout went into
 * re-seeding the same dataset between spec files. The endpoint itself is
 * idempotent (ON CONFLICT DO NOTHING), so loading once at the start is
 * sufficient; the per-spec helper now short-circuits when data is already
 * present (see helpers/demo-data.ts).
 */
export default async function globalSetup(_config: FullConfig): Promise<void> {
  const ctx = await request.newContext()
  try {
    const resp = await ctx.post(`${BACKEND_URL}/api/settings/demo-data/load`, {
      timeout: 120_000,
    })
    if (!resp.ok()) {
      const body = await resp.text()
      throw new Error(`globalSetup: failed to load demo data (${resp.status()}): ${body}`)
    }
    // eslint-disable-next-line no-console
    console.log('[globalSetup] demo data loaded')
  } finally {
    await ctx.dispose()
  }
}
