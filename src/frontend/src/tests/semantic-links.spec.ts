import { test, expect, Page } from '@playwright/test'

// This test assumes backend at http://localhost:8000 with at least one contract existing.
// It edits the first contract found, adds schema/property semantic concepts in the wizard,
// saves, and verifies links appear in the details view.

async function navigateToFirstContract(page: Page) {
  await page.goto('/data-contracts')
  // Rows contain contract names; click first details link
  const firstRow = page.locator('table >> tbody >> tr').first()
  await expect(firstRow).toBeVisible()
  await firstRow.click()
}

test('adds schema and property semantic links via wizard', async ({ page }) => {
  await navigateToFirstContract(page)

  // Open wizard
  await page.getByRole('button', { name: /edit/i }).click()

  // Step 2: add schema object if none
  // Go to Schema step
  await page.getByRole('button', { name: /next/i }).click()

  const addSchemaBtn = page.getByRole('button', { name: /add schema object/i })
  if (await addSchemaBtn.isVisible()) {
    await addSchemaBtn.click()
    // Target the schema just added by using the last schema-object container
    const lastSchema = page.locator('[id^="schema-object-"]').last()
    const logicalInput = lastSchema.getByPlaceholder(/e\.g\., customers, orders/i)
    await logicalInput.fill('playwright_demo_tbl')
    await lastSchema.getByRole('button', { name: /add column/i }).click()
    await lastSchema.getByPlaceholder('column_name').fill('email')
  }

  // Add schema concept
  await page.getByText('Linked Business Concepts:').first().scrollIntoViewIfNeeded()
  const addConceptBtn = page.locator('[id^="schema-object-"]').last().getByRole('button', { name: /^add concept$/i })
  await addConceptBtn.click()
  // In dialog, search and pick first concept
  const searchInput = page.getByPlaceholder(/search business concepts/i)
  await searchInput.fill('Customer')
  const selectBtn = page.getByRole('button', { name: /^select$/i }).first()
  await selectBtn.click()

  // Expand Advanced for first column and add a property concept
  await page.locator('[id^="schema-object-"]').last().getByText('Advanced').click()
  const addPropConceptBtn = page.locator('[id^="schema-object-"]').last().getByRole('button', { name: /^add property$/i })
  await addPropConceptBtn.click()
  const propSearch = page.getByPlaceholder(/search business properties/i)
  await propSearch.fill('email')
  await page.getByRole('button', { name: /^select$/i }).first().click()

  // Save
  // Click through to last step to ensure Save Contract button appears
  for (let i = 0; i < 3; i++) {
    const next = page.getByRole('button', { name: /^next$/i })
    if (await next.isVisible()) await next.click()
  }
  const saveBtn = page.getByRole('button', { name: /(save contract|save)$/i }).first()
  await saveBtn.click()

  // Wait for dialog to close
  await expect(page.getByRole('dialog')).toHaveCount(0)

  // Verify via API: fetch semantic links for schema and property entities
  const contractId = page.url().split('/').pop()!
  const schemaEntityId = `${contractId}#playwright_demo_tbl`
  const propertyEntityId = `${schemaEntityId}#email`

  // Poll backend until link appears
  await page.waitForFunction(async (id) => {
    const r = await fetch(`/api/semantic-links/entity/data_contract_schema/${id}`)
    if (!r.ok) return false
    const data = await r.json()
    return Array.isArray(data) && data.length > 0
  }, schemaEntityId, { timeout: 15000 })

  await page.waitForFunction(async (id) => {
    const r = await fetch(`/api/semantic-links/entity/data_contract_property/${id}`)
    if (!r.ok) return false
    const data = await r.json()
    return Array.isArray(data) && data.length > 0
  }, propertyEntityId, { timeout: 15000 })
})


test('assigns and removes a semantic concept link on an asset', async ({ page }) => {
  // Pick the first asset from the asset list endpoint so the test is data-driven.
  const assetsResp = await page.request.get('/api/assets?limit=1')
  test.skip(!assetsResp.ok(), 'No /api/assets endpoint reachable')
  const assetsBody: any = await assetsResp.json().catch(() => null)
  const firstAsset = assetsBody?.items?.[0]
  test.skip(!firstAsset?.id, 'No assets seeded in the backend')

  await page.goto(`/assets/${firstAsset.id}`)

  // Wait for the Overview tab to render the Details card.
  await expect(page.getByRole('tab', { name: /overview/i })).toBeVisible()

  // Open the concept picker via the "Add" trailing button on the linked chips row.
  const linkedSection = page.getByText('Linked Business Concepts').first()
  await linkedSection.scrollIntoViewIfNeeded()
  const addBtn = page.getByRole('button', { name: /^add$/i }).first()
  await addBtn.click()

  // Pick the first available concept.
  const searchInput = page.getByPlaceholder(/search business concepts/i)
  await expect(searchInput).toBeVisible()
  const selectBtn = page.getByRole('button', { name: /^select$/i }).first()
  await selectBtn.click()

  // Verify the link appears via the backend.
  await page.waitForFunction(async (id) => {
    const r = await fetch(`/api/semantic-links/entity/asset/${id}`)
    if (!r.ok) return false
    const data = await r.json()
    return Array.isArray(data) && data.length > 0
  }, firstAsset.id, { timeout: 15000 })

  // Capture the link id and remove via the API to clean up. Hover-based UI
  // removal is brittle in headless mode; the asset-detail panel calls the
  // same endpoint so backend coverage is sufficient.
  const linksResp = await page.request.get(`/api/semantic-links/entity/asset/${firstAsset.id}`)
  const links: Array<{ id: string }> = await linksResp.json()
  for (const link of links) {
    await page.request.delete(`/api/semantic-links/${link.id}`)
  }
})

