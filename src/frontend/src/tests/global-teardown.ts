import { request, FullConfig } from '@playwright/test'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

/**
 * Clear demo data once after the entire Playwright run.
 *
 * Mirrors global-setup.ts. Failures here are logged but never thrown — the
 * suite has already finished and we don't want teardown to flip a green run
 * red. Local runs can also skip teardown so devs keep their seeded DB.
 */
export default async function globalTeardown(_config: FullConfig): Promise<void> {
  if (!process.env.CI) {
    // eslint-disable-next-line no-console
    console.log('[globalTeardown] skipping clear (not in CI)')
    return
  }

  const ctx = await request.newContext()
  try {
    const resp = await ctx.delete(`${BACKEND_URL}/api/settings/demo-data`, {
      timeout: 60_000,
    })
    if (!resp.ok()) {
      const body = await resp.text()
      // eslint-disable-next-line no-console
      console.warn(`[globalTeardown] clear failed (${resp.status()}): ${body}`)
      return
    }
    // eslint-disable-next-line no-console
    console.log('[globalTeardown] demo data cleared')
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[globalTeardown] clear errored:', err)
  } finally {
    await ctx.dispose()
  }
}
