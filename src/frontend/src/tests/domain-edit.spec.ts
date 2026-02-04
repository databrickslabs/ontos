import { test, expect, Page } from '@playwright/test'

async function navigateToFirstDomain(page: Page) {
  await page.goto('/data-domains')
  const firstRow = page.locator('table >> tbody >> tr').first()
  await expect(firstRow).toBeVisible()
  // Open row menu and click View Details for reliable navigation
  await firstRow.getByRole('button', { name: 'Open menu' }).click()
  await page.getByRole('menuitem', { name: /view details/i }).click()
}

test('edits a data domain from details view', async ({ page }) => {
  await navigateToFirstDomain(page)

  // Open edit dialog
  // The details page has multiple buttons; target the top bar Edit
  // Note: topBar locator available for future use if needed
  void page.locator('div').filter({ hasText: /^Back to List/ }).first().locator('..')
  await page.getByRole('button', { name: /^edit$/i }).first().click()

  // Ensure dialog is visible
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()

  // Change the description field; keep name to avoid collisions
  const desc = dialog.getByLabel(/^description$/i)
  await desc.fill('Updated via Playwright')

  // Ensure required Owners field is filled
  const owners = dialog.getByLabel(/^owners/i)
  const ownersValue = await owners.inputValue().catch(() => '')
  if (!ownersValue) {
    await owners.fill('system.init@app.dev')
  }

  // Save
  const saveBtn = dialog.getByRole('button', { name: /(save changes|save|create)/i }).first()
  await saveBtn.click()

  // Wait for dialog to close
  await expect(dialog).toHaveCount(0)

  // Verify the description updated in the details view
  await expect(page.getByText('Updated via Playwright')).toBeVisible()
})


