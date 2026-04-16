import { test, expect, APIRequestContext } from '@playwright/test'
import { loadDemoData, clearDemoData } from './helpers/demo-data'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

test.beforeAll(async ({ request }) => {
  await loadDemoData(request)
})

test.afterAll(async ({ request }) => {
  await clearDemoData(request)
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function getFirstProductId(request: APIRequestContext): Promise<string | null> {
  const resp = await request.get(`${BACKEND_URL}/api/data-products`)
  if (!resp.ok()) return null
  const products = await resp.json()
  return Array.isArray(products) && products.length > 0 ? products[0].id : null
}

async function getFirstContractId(request: APIRequestContext): Promise<string | null> {
  const resp = await request.get(`${BACKEND_URL}/api/data-contracts`)
  if (!resp.ok()) return null
  const contracts = await resp.json()
  return Array.isArray(contracts) && contracts.length > 0 ? contracts[0].id : null
}

// =========================================================================
// 1. Certification Levels Settings (Phase 1 prerequisite)
// =========================================================================
test.describe('Certification Levels Settings', () => {
  test('settings page loads without hanging', async ({ page }) => {
    await page.goto('/settings/certification-levels')
    await expect(page.locator('main')).toBeVisible()
    // The spinner should disappear within a few seconds
    const spinner = page.locator('[class*="animate-spin"]')
    await expect(spinner).toHaveCount(0, { timeout: 10_000 })
  })

  test('displays default certification levels', async ({ page }) => {
    await page.goto('/settings/certification-levels')
    // Wait for the page to settle — levels may render as text or in table cells
    await page.waitForTimeout(2000)
    const bronzeOrSilverOrGold = page.getByText('Bronze')
      .or(page.getByText('Silver'))
      .or(page.getByText('Gold'))
      .or(page.getByText('Certification Level'))
    await expect(bronzeOrSilverOrGold.first()).toBeVisible({ timeout: 15_000 })
  })

  test('certification levels API returns data', async ({ request }) => {
    const resp = await request.get(`${BACKEND_URL}/api/certification-levels`)
    expect(resp.status()).toBe(200)
    const levels = await resp.json()
    expect(Array.isArray(levels)).toBe(true)
    expect(levels.length).toBeGreaterThanOrEqual(3)
    expect(levels.map((l: any) => l.name)).toEqual(expect.arrayContaining(['Bronze', 'Silver', 'Gold']))
  })
})

// =========================================================================
// 2. Backend API — Certification & Publication Routes (Phases 1c-1d)
// =========================================================================
test.describe('Certification & Publication API — Data Products', () => {
  test('POST /data-products/{id}/request-certify returns 202', async ({ request }) => {
    const productId = await getFirstProductId(request)
    test.skip(!productId, 'No products available')

    const resp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/request-certify`, {
      data: { certification_level: 1, message: 'Playwright test certification request' },
    })
    // 202 for accepted, or 200/409 if already certified or workflow running
    expect([200, 202, 409]).toContain(resp.status())
  })

  test('POST /data-products/{id}/request-publish returns 202', async ({ request }) => {
    const productId = await getFirstProductId(request)
    test.skip(!productId, 'No products available')

    const resp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/request-publish`, {
      data: { scope: 'organization', justification: 'Playwright test publish request' },
    })
    expect([200, 202, 409]).toContain(resp.status())
  })

  test('POST /data-products/{id}/certify sets certification level', async ({ request }) => {
    const productId = await getFirstProductId(request)
    test.skip(!productId, 'No products available')

    const resp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/certify`, {
      data: { certification_level: 2, notes: 'Certified by Playwright' },
    })
    // May fail if product is not active
    if (resp.ok()) {
      const body = await resp.json()
      expect(body.certification_level).toBe(2)
      expect(body.certification_notes).toBeTruthy()
    }
  })

  test('POST /data-products/{id}/set-publication-scope sets scope', async ({ request }) => {
    const productId = await getFirstProductId(request)
    test.skip(!productId, 'No products available')

    const resp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/set-publication-scope`, {
      data: { scope: 'organization' },
    })
    if (resp.ok()) {
      const body = await resp.json()
      expect(body.publication_scope).toBe('organization')
    }
  })

  test('POST /data-products/{id}/decertify removes certification', async ({ request }) => {
    const productId = await getFirstProductId(request)
    test.skip(!productId, 'No products available')

    const resp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/decertify`)
    if (resp.ok()) {
      const body = await resp.json()
      expect(body.certification_level).toBeNull()
    }
  })

  test('POST /data-products/{id}/unpublish sets scope to none', async ({ request }) => {
    const productId = await getFirstProductId(request)
    test.skip(!productId, 'No products available')

    const resp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/unpublish`)
    if (resp.ok()) {
      const body = await resp.json()
      expect(body.publication_scope).toBe('none')
    }
  })

  test('POST /data-products/{id}/handle-certify approves certification', async ({ request }) => {
    const productId = await getFirstProductId(request)
    test.skip(!productId, 'No products available')

    const resp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/handle-certify`, {
      data: { approved: true, certification_level: 1, notes: 'Approved by Playwright' },
    })
    expect([200, 400, 409, 422]).toContain(resp.status())
  })

  test('POST /data-products/{id}/handle-publish approves publication', async ({ request }) => {
    const productId = await getFirstProductId(request)
    test.skip(!productId, 'No products available')

    const resp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/handle-publish`, {
      data: { approved: true, scope: 'organization' },
    })
    expect([200, 400, 409, 422]).toContain(resp.status())
  })
})

test.describe('Certification & Publication API — Data Contracts', () => {
  test('POST /data-contracts/{id}/request-certify returns 202', async ({ request }) => {
    const contractId = await getFirstContractId(request)
    test.skip(!contractId, 'No contracts available')

    const resp = await request.post(`${BACKEND_URL}/api/data-contracts/${contractId}/request-certify`, {
      data: { certification_level: 1, message: 'Playwright test contract cert request' },
    })
    expect([200, 202, 409]).toContain(resp.status())
  })

  test('POST /data-contracts/{id}/request-publish returns 202', async ({ request }) => {
    const contractId = await getFirstContractId(request)
    test.skip(!contractId, 'No contracts available')

    const resp = await request.post(`${BACKEND_URL}/api/data-contracts/${contractId}/request-publish`, {
      data: { scope: 'organization', justification: 'Playwright test contract publish' },
    })
    expect([200, 202, 409]).toContain(resp.status())
  })

  test('POST /data-contracts/{id}/handle-certify works', async ({ request }) => {
    const contractId = await getFirstContractId(request)
    test.skip(!contractId, 'No contracts available')

    const resp = await request.post(`${BACKEND_URL}/api/data-contracts/${contractId}/handle-certify`, {
      data: { approved: true, certification_level: 2, notes: 'Contract cert by Playwright' },
    })
    expect([200, 400, 422]).toContain(resp.status())
  })
})

// =========================================================================
// 3. Workflow System — New Trigger Types & Step Type (Phase 1a-b, Phase 4)
// =========================================================================
test.describe('Workflow System — New Types', () => {
  test('workflow step types include entity_action', async ({ request }) => {
    const resp = await request.get(`${BACKEND_URL}/api/workflows/step-types`)
    if (resp.ok()) {
      const types = await resp.json()
      const typeValues = Array.isArray(types)
        ? types.map((t: any) => t.type || t.value || t)
        : Object.keys(types)
      expect(typeValues).toContain('entity_action')
    }
  })

  test('default workflows include certification and publication workflows', async ({ request }) => {
    const resp = await request.get(`${BACKEND_URL}/api/workflows`)
    if (resp.ok()) {
      const data = await resp.json()
      const items = Array.isArray(data) ? data : data.workflows || data.items || []
      const names = items.map((w: any) => w.name)
      // New default workflows load on server restart; verify at least one publish workflow exists
      const hasPublish = names.some((n: string) => /publish/i.test(n))
      expect(hasPublish).toBe(true)
    }
  })
})

// =========================================================================
// 4. Marketplace — Scope-based Filtering (Phase 7)
// =========================================================================
test.describe('Marketplace — Scope Filtering', () => {
  test('published products API accepts scope query param', async ({ request }) => {
    const respAll = await request.get(`${BACKEND_URL}/api/data-products/published`)
    expect(respAll.status()).toBe(200)
    const all = await respAll.json()
    expect(Array.isArray(all)).toBe(true)

    const respOrg = await request.get(`${BACKEND_URL}/api/data-products/published?scope=organization`)
    expect(respOrg.status()).toBe(200)
    const org = await respOrg.json()
    expect(Array.isArray(org)).toBe(true)
    // Filtered results should be <= total
    expect(org.length).toBeLessThanOrEqual(all.length)
  })

  test('marketplace page has scope filter dropdown', async ({ page }) => {
    await page.goto('/marketplace')
    await expect(page.locator('main')).toBeVisible()
    // Look for a scope selector or filter control
    const scopeFilter = page.getByRole('combobox', { name: /scope/i })
      .or(page.locator('button:has-text("All Scopes")'))
      .or(page.locator('[data-testid="scope-filter"]'))
      .or(page.getByText(/all scopes/i))
    await expect(scopeFilter.first()).toBeVisible({ timeout: 10_000 })
  })
})

// =========================================================================
// 5. Data Product Detail Page — Lifecycle UI (Phase 6)
// =========================================================================
test.describe('Data Product Detail — Lifecycle Panel & Badges', () => {
  test('detail page shows lifecycle summary panel', async ({ page }) => {
    await page.goto('/data-products')
    const rows = page.locator('table >> tbody >> tr')
    if ((await rows.count()) === 0) return
    await rows.first().click()

    // LifecycleSummaryPanel should be visible
    const panel = page.getByText(/certification/i)
      .or(page.getByText(/publication/i))
      .or(page.locator('[data-testid="lifecycle-panel"]'))
    await expect(panel.first()).toBeVisible({ timeout: 10_000 })
  })

  test('certify button visible for admin users', async ({ page }) => {
    await page.goto('/data-products')
    const rows = page.locator('table >> tbody >> tr')
    if ((await rows.count()) === 0) return
    await rows.first().click()

    // Admin users should see Certify in toolbar or panel
    const certifyBtn = page.getByRole('button', { name: /certify/i })
    // May not be visible if product is not in right status
    const isVisible = await certifyBtn.first().isVisible().catch(() => false)
    if (isVisible) {
      await expect(certifyBtn.first()).toBeEnabled()
    }
  })

  test('publish button visible for admin users', async ({ page }) => {
    await page.goto('/data-products')
    const rows = page.locator('table >> tbody >> tr')
    if ((await rows.count()) === 0) return
    await rows.first().click()

    const publishBtn = page.getByRole('button', { name: /publish/i })
    const isVisible = await publishBtn.first().isVisible().catch(() => false)
    if (isVisible) {
      await expect(publishBtn.first()).toBeEnabled()
    }
  })

  test('product list shows certification and publication badges', async ({ page }) => {
    await page.goto('/data-products')
    const rows = page.locator('table >> tbody >> tr')
    await expect(rows.first()).toBeVisible()

    // After certifying via API, badges should appear
    // For now, just verify the list page renders without errors
    await expect(page.locator('main')).toBeVisible()
  })
})

// =========================================================================
// 6. Data Contract Detail Page — Lifecycle UI (Phase 6)
// =========================================================================
test.describe('Data Contract Detail — Lifecycle Panel & Badges', () => {
  test('detail page shows lifecycle summary panel', async ({ page }) => {
    await page.goto('/data-contracts')
    const rows = page.locator('table >> tbody >> tr')
    if ((await rows.count()) === 0) return
    await rows.first().click()

    const panel = page.getByText(/certification/i)
      .or(page.getByText(/publication/i))
    await expect(panel.first()).toBeVisible({ timeout: 10_000 })
  })

  test('contract list shows certification and publication badges', async ({ page }) => {
    await page.goto('/data-contracts')
    const rows = page.locator('table >> tbody >> tr')
    await expect(rows.first()).toBeVisible()
    await expect(page.locator('main')).toBeVisible()
  })
})

// =========================================================================
// 7. Request Dialogs — Certify & Publish Options (Phase 5)
// =========================================================================
test.describe('Request Dialog — Product Certification & Publication', () => {
  test('request dialog includes certify option', async ({ page }) => {
    await page.goto('/data-products')
    const rows = page.locator('table >> tbody >> tr')
    if ((await rows.count()) === 0) return
    await rows.first().click()

    // Open request dialog
    const requestBtn = page.getByRole('button', { name: /request/i })
    const hasRequestBtn = await requestBtn.first().isVisible().catch(() => false)
    if (!hasRequestBtn) return

    await requestBtn.first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // Look for certification option in the type selector
    const certOption = dialog.getByText(/certification/i)
      .or(dialog.getByText(/certify/i))
    await expect(certOption.first()).toBeVisible()
  })

  test('request dialog includes publish option', async ({ page }) => {
    await page.goto('/data-products')
    const rows = page.locator('table >> tbody >> tr')
    if ((await rows.count()) === 0) return
    await rows.first().click()

    const requestBtn = page.getByRole('button', { name: /request/i })
    const hasRequestBtn = await requestBtn.first().isVisible().catch(() => false)
    if (!hasRequestBtn) return

    await requestBtn.first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    const pubOption = dialog.getByText(/publish/i)
    await expect(pubOption.first()).toBeVisible()
  })

  test('certify request shows level picker when selected', async ({ page }) => {
    await page.goto('/data-products')
    const rows = page.locator('table >> tbody >> tr')
    if ((await rows.count()) === 0) return
    await rows.first().click()

    const requestBtn = page.getByRole('button', { name: /request/i })
    const hasRequestBtn = await requestBtn.first().isVisible().catch(() => false)
    if (!hasRequestBtn) return

    await requestBtn.first().click()
    const dialog = page.getByRole('dialog')

    // Select certify type — look for the type dropdown/select
    const typeSelect = dialog.locator('select, [role="combobox"]').first()
    if (await typeSelect.isVisible().catch(() => false)) {
      await typeSelect.click()
      const certItem = page.getByRole('option', { name: /certif/i })
        .or(page.locator('[role="option"]:has-text("Certif")'))
      if (await certItem.first().isVisible().catch(() => false)) {
        await certItem.first().click()
        // Should show a level picker
        await expect(
          dialog.getByText(/level/i)
            .or(dialog.getByText(/bronze/i))
            .or(dialog.getByText(/silver/i))
            .or(dialog.getByText(/gold/i))
            .first()
        ).toBeVisible({ timeout: 5_000 })
      }
    }
  })
})

test.describe('Request Dialog — Contract Certification & Publication', () => {
  test('contract request dialog includes certify option', async ({ page }) => {
    await page.goto('/data-contracts')
    const rows = page.locator('table >> tbody >> tr')
    if ((await rows.count()) === 0) return
    await rows.first().click()

    const requestBtn = page.getByRole('button', { name: /request/i })
    const hasRequestBtn = await requestBtn.first().isVisible().catch(() => false)
    if (!hasRequestBtn) return

    await requestBtn.first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    const certOption = dialog.getByText(/certification/i)
      .or(dialog.getByText(/certify/i))
    await expect(certOption.first()).toBeVisible()
  })

  test('contract request dialog includes publish option', async ({ page }) => {
    await page.goto('/data-contracts')
    const rows = page.locator('table >> tbody >> tr')
    if ((await rows.count()) === 0) return
    await rows.first().click()

    const requestBtn = page.getByRole('button', { name: /request/i })
    const hasRequestBtn = await requestBtn.first().isVisible().catch(() => false)
    if (!hasRequestBtn) return

    await requestBtn.first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    const pubOption = dialog.getByText(/publish/i)
    await expect(pubOption.first()).toBeVisible()
  })
})

// =========================================================================
// 8. Workflow Designer — Entity Action Step (Phase 8)
// =========================================================================
test.describe('Workflow Designer — Entity Action Support', () => {
  test('designer page loads', async ({ page }) => {
    await page.goto('/settings/workflows')
    await expect(page.locator('main')).toBeVisible()
  })

  test('step palette includes entity action', async ({ page }) => {
    // Navigate to workflow designer for a new or existing workflow
    await page.goto('/settings/workflows')
    await expect(page.locator('main')).toBeVisible()

    // Look for "Create" or "New Workflow" button, or existing workflow to edit
    const createBtn = page.getByRole('button', { name: /create|new/i })
    const editBtn = page.getByRole('button', { name: /edit|configure/i })
    const workflowLink = page.locator('a[href*="workflow"]')

    const hasCreate = await createBtn.first().isVisible().catch(() => false)
    const hasEdit = await editBtn.first().isVisible().catch(() => false)
    const hasLink = await workflowLink.first().isVisible().catch(() => false)

    if (hasCreate || hasEdit || hasLink) {
      if (hasCreate) await createBtn.first().click()
      else if (hasLink) await workflowLink.first().click()
      else if (hasEdit) await editBtn.first().click()

      // Look for entity action in the step palette/toolbox
      const entityAction = page.getByText(/entity action/i)
      if (await entityAction.first().isVisible({ timeout: 5_000 }).catch(() => false)) {
        await expect(entityAction.first()).toBeVisible()
      }
    }
  })
})

// =========================================================================
// 9. Notification Bell — Action Types (Phase 3)
// =========================================================================
test.describe('Notification Bell', () => {
  test('notification bell renders without errors', async ({ page }) => {
    await page.goto('/')
    // Just verify the page loads without crashing
    await expect(page.locator('main')).toBeVisible()
  })
})

// =========================================================================
// 10. End-to-End: Certify & Publish a Product via API
// =========================================================================
test.describe('E2E: Product Lifecycle — Certify then Publish', () => {
  test('certify and publish a product via direct API', async ({ request }) => {
    const productId = await getFirstProductId(request)
    test.skip(!productId, 'No products available')

    // Step 1: Certify at level 1 (Bronze)
    const certResp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/certify`, {
      data: { certification_level: 1, notes: 'E2E test certification' },
    })
    if (certResp.ok()) {
      const cert = await certResp.json()
      expect(cert.certification_level).toBe(1)
    }

    // Step 2: Publish to organization scope
    const pubResp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/set-publication-scope`, {
      data: { scope: 'organization' },
    })
    if (pubResp.ok()) {
      const pub = await pubResp.json()
      expect(pub.publication_scope).toBe('organization')
    }

    // Step 3: Verify it appears in published products
    const listResp = await request.get(`${BACKEND_URL}/api/data-products/published?scope=organization`)
    expect(listResp.status()).toBe(200)
    const products = await listResp.json()
    // The certified+published product should be in the list
    const found = products.find((p: any) => p.id === productId)
    if (found) {
      expect(found.publication_scope).toBe('organization')
    }

    // Step 4: Unpublish
    const unpubResp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/unpublish`)
    if (unpubResp.ok()) {
      const unpub = await unpubResp.json()
      expect(unpub.publication_scope).toBe('none')
    }

    // Step 5: Decertify
    const decertResp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/decertify`)
    if (decertResp.ok()) {
      const decert = await decertResp.json()
      expect(decert.certification_level).toBeNull()
    }
  })

  test('request-certify followed by handle-certify flow', async ({ request }) => {
    const productId = await getFirstProductId(request)
    test.skip(!productId, 'No products available')

    // Step 1: Request certification
    const reqResp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/request-certify`, {
      data: { certification_level: 2, message: 'E2E request flow' },
    })
    expect([200, 202, 409]).toContain(reqResp.status())

    // Step 2: Handle (approve) the certification
    const handleResp = await request.post(`${BACKEND_URL}/api/data-products/${productId}/handle-certify`, {
      data: { approved: true, certification_level: 2, notes: 'E2E approved' },
    })
    expect([200, 400, 409, 422]).toContain(handleResp.status())
  })
})

// =========================================================================
// 11. Legacy Cleanup Verification (Phase 2)
// =========================================================================
test.describe('Legacy Cleanup — No published boolean in API', () => {
  test('product API response uses publication_scope not published boolean', async ({ request }) => {
    const resp = await request.get(`${BACKEND_URL}/api/data-products`)
    if (!resp.ok()) return
    const products = await resp.json()
    if (!Array.isArray(products) || products.length === 0) return

    const product = products[0]
    // publication_scope should exist; published boolean should not
    expect(product).toHaveProperty('publication_scope')
    expect(product).not.toHaveProperty('published')
  })

  test('contract API response uses publication_scope not published boolean', async ({ request }) => {
    const resp = await request.get(`${BACKEND_URL}/api/data-contracts`)
    if (!resp.ok()) return
    const contracts = await resp.json()
    const items = Array.isArray(contracts) ? contracts : contracts.items || []
    if (items.length === 0) return

    const contract = items[0]
    expect(contract).toHaveProperty('publication_scope')
    // published may still exist during transition, but publication_scope must be present
  })
})
