import { test, expect } from '@playwright/test'
import { loadDemoData, clearDemoData } from './helpers/demo-data'

test.beforeAll(async ({ request }) => {
  await loadDemoData(request)
})

test.afterAll(async ({ request }) => {
  await clearDemoData(request)
})

// ---------------------------------------------------------------------------
// CUJ-8  Data Products — CRUD & Lifecycle
// ---------------------------------------------------------------------------
test.describe('CUJ-8 — Data Products', () => {
  test('lists existing data products', async ({ page }) => {
    await page.goto('/data-products')
    const rows = page.locator('table >> tbody >> tr')
    await expect(rows.first()).toBeVisible()
    expect(await rows.count()).toBeGreaterThan(0)
  })

  test('my-products page loads', async ({ page }) => {
    await page.goto('/my-products')
    // Page should render without error
    await expect(page.locator('main')).toBeVisible()
  })

  test.describe.serial('create, view, and delete data product', () => {
    const productName = `PW Product ${Date.now()}`

    test('creates a new data product', async ({ page }) => {
      await page.goto('/data-products')
      await page.getByRole('button', { name: /create product/i }).click()

      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      // Fill required fields
      await dialog.getByLabel(/product name/i).fill(productName)

      // Version should have a default; fill if empty
      const versionInput = dialog.getByLabel(/version/i)
      if (await versionInput.isVisible()) {
        const val = await versionInput.inputValue().catch(() => '')
        if (!val) await versionInput.fill('1.0.0')
      }

      await dialog.getByRole('button', { name: /create product/i }).click()
      await expect(dialog).toHaveCount(0)
    })

    test('views data product detail page', async ({ page }) => {
      await page.goto('/data-products')
      // The products table paginates; filter so the new product is on page 1.
      await page.getByPlaceholder(/filter/i).fill(productName)
      const row = page.locator('table >> tbody >> tr', { hasText: productName })
      await row.first().click()

      // Detail page should show key sections (name appears in breadcrumb + header)
      await expect(page.getByText(productName).first()).toBeVisible()
      // Port sections are labelled "Deliverables (n)" / "Consumables (n)".
      await expect(
        page.getByText(/^deliverables \(\d+\)$/i)
          .or(page.getByText(/^consumables \(\d+\)$/i))
          .first()
      ).toBeVisible()
    })

    test('lifecycle action buttons are visible on detail page', async ({ page }) => {
      await page.goto('/data-products')
      const rows = page.locator('table >> tbody >> tr')
      await rows.first().click()

      // At least one lifecycle button should be present
      const submitCert = page.getByRole('button', { name: /submit for certification/i })
      const certify = page.getByRole('button', { name: /^certify$/i })
      const approve = page.getByRole('button', { name: /^approve$/i })
      const publish = page.getByRole('button', { name: /^publish$/i })

      await expect(
        submitCert.or(certify).or(approve).or(publish)
      ).toBeVisible()
    })

    test('deletes the created data product', async ({ page }) => {
      await page.goto('/data-products')
      await page.getByPlaceholder(/filter/i).fill(productName)

      const row = page.locator('table >> tbody >> tr', { hasText: productName })
      const deleteBtn = row.getByTitle(/delete/i)
        .or(row.getByRole('button', { name: /delete/i }))

      // Register native confirm() handler before clicking
      page.on('dialog', (d) => d.accept())
      await deleteBtn.first().click()

      await expect(row).toHaveCount(0, { timeout: 5_000 })
    })
  })
})

// ---------------------------------------------------------------------------
// CUJ-11  Add Metadata to Data Products
// ---------------------------------------------------------------------------
test.describe('CUJ-11 — Data Product Metadata', () => {
  test('detail page shows metadata sections', async ({ page }) => {
    await page.goto('/data-products')
    const rows = page.locator('table >> tbody >> tr')
    const count = await rows.count()
    if (count === 0) return

    await rows.first().click()

    // Verify metadata-related sections exist
    await expect(
      page.getByRole('heading', { name: /metadata/i })
        .or(page.getByText(/attached documents/i))
        .or(page.getByText(/custom properties/i))
        .first()
    ).toBeVisible()
  })

  test('detail page shows ratings or comments section', async ({ page }) => {
    await page.goto('/data-products')
    const rows = page.locator('table >> tbody >> tr')
    const count = await rows.count()
    if (count === 0) return

    await rows.first().click()

    await expect(
      page.getByText(/comments/i)
        .or(page.getByText(/ratings/i))
        .or(page.getByText(/feedback/i))
        .first()
    ).toBeVisible()
  })
})
