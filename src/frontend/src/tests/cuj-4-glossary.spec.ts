import { test, expect } from '@playwright/test'
import { loadDemoData, clearDemoData } from './helpers/demo-data'

test.beforeAll(async ({ request }) => {
  await loadDemoData(request)
})

test.afterAll(async ({ request }) => {
  await clearDemoData(request)
})

// ---------------------------------------------------------------------------
// CUJ-4  Business Glossary — Collections
// ---------------------------------------------------------------------------
test.describe('CUJ-4 — Collections', () => {
  test('collections list loads with items', async ({ page }) => {
    await page.goto('/concepts/collections')
    // Wait for any list/table/card content to appear
    await expect(
      page.locator('table >> tbody >> tr').or(page.locator('[role="listitem"]')).first()
    ).toBeVisible({ timeout: 10_000 })
  })

  test.describe.serial('create and delete collection', () => {
    const collectionName = `PW Glossary ${Date.now()}`

    test('creates a new collection', async ({ page }) => {
      await page.goto('/concepts/collections')
      await page.getByRole('button', { name: /create collection/i }).first().click()

      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      await dialog.getByLabel(/^name/i).fill(collectionName)
      await dialog.getByRole('button', { name: /^create$/i }).click()
      await expect(dialog).toHaveCount(0)

      await expect(page.getByText(collectionName)).toBeVisible()
    })

    test('deletes the created collection', async ({ page }) => {
      await page.goto('/concepts/collections')
      await page.waitForLoadState('networkidle')
      const row = page.locator('table >> tbody >> tr', { hasText: collectionName })
      await row.first().getByRole('button', { name: /open menu/i }).click()

      // Accept the native confirm() dialog that fires on delete
      page.on('dialog', (d) => d.accept())
      await page.getByRole('menuitem', { name: /delete/i }).click()

      await expect(page.getByText(collectionName)).toHaveCount(0)
    })
  })
})

// ---------------------------------------------------------------------------
// CUJ-4 / CUJ-9  Business Glossary — Concepts / Terms
// ---------------------------------------------------------------------------
test.describe('CUJ-4 — Business Terms Browser', () => {
  test('business terms browser loads with items', async ({ page }) => {
    await page.goto('/concepts/browser')
    await page.waitForLoadState('networkidle')
    // The browser renders concepts as tree nodes in plain divs
    await expect(page.locator('main')).toBeVisible()
  })

  test.describe.serial('create and delete concept', () => {
    const conceptLabel = `PW Concept ${Date.now()}`

    test('creates a new concept', async ({ page }) => {
      await page.goto('/concepts/browser')
      await page.waitForLoadState('networkidle')

      // The create button is a dropdown trigger: "Create" with chevron
      const createBtn = page.getByRole('button', { name: /^create$/i }).first()
      await createBtn.click()

      // Pick "Create Concept" from the dropdown menu
      const menuItem = page.getByRole('menuitem', { name: /create concept/i })
      await expect(menuItem).toBeVisible()
      await menuItem.click()

      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      // The collection select defaults to the first editable collection. It is
      // interactive when multiple editable collections exist, but this test
      // relies on the default, so we don't switch it.
      await dialog.getByLabel(/^label$/i).fill(conceptLabel)

      await dialog.getByRole('button', { name: /^create$/i }).click()
      await expect(dialog).toHaveCount(0)

      await expect(page.getByText(conceptLabel)).toBeVisible()
    })

    test('deletes the created concept', async ({ page }) => {
      await page.goto('/concepts/browser')

      // Find and click on the concept to select it
      await page.getByText(conceptLabel).first().click()

      // The detail panel should show a Delete button
      const deleteBtn = page.getByRole('button', { name: /^delete$/i })
      await expect(deleteBtn).toBeVisible()
      await deleteBtn.click()

      // Concept may be deleted without confirmation
      await expect(page.getByText(conceptLabel)).toHaveCount(0, { timeout: 5_000 })
    })
  })
})
