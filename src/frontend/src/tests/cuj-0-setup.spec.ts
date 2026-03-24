import { test, expect } from '@playwright/test'
import { loadDemoData, clearDemoData } from './helpers/demo-data'

test.beforeAll(async ({ request }) => {
  await loadDemoData(request)
})

test.afterAll(async ({ request }) => {
  await clearDemoData(request)
})

// ---------------------------------------------------------------------------
// CUJ-0.0  Data Domains
// ---------------------------------------------------------------------------
test.describe('CUJ-0.0 — Data Domains CRUD', () => {
  test('lists existing domains', async ({ page }) => {
    await page.goto('/settings/data-domains')
    const rows = page.locator('table >> tbody >> tr')
    await expect(rows.first()).toBeVisible()
    expect(await rows.count()).toBeGreaterThan(0)
  })

  test.describe.serial('create, view, edit, delete domain', () => {
    const domainName = `PW Domain ${Date.now()}`

    test('creates a new domain', async ({ page }) => {
      await page.goto('/settings/data-domains')
      await page.getByRole('button', { name: /add new domain/i }).click()

      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      await dialog.getByLabel(/^name/i).fill(domainName)
      await dialog.getByLabel(/description/i).fill('Created by Playwright CUJ test')

      await dialog.getByRole('button', { name: /create domain/i }).click()
      await expect(dialog).toHaveCount(0)

      await expect(page.getByText(domainName)).toBeVisible()
    })

    test('views domain details', async ({ page }) => {
      await page.goto('/settings/data-domains')
      const row = page.locator('table >> tbody >> tr', { hasText: domainName })
      await row.getByRole('button', { name: 'Open menu' }).click()
      await page.getByRole('menuitem', { name: /view details/i }).click()

      await expect(page.getByText(domainName)).toBeVisible()
      await expect(page.getByText('Created by Playwright CUJ test')).toBeVisible()
    })

    test('edits domain description', async ({ page }) => {
      await page.goto('/settings/data-domains')
      const row = page.locator('table >> tbody >> tr', { hasText: domainName })
      await row.getByRole('button', { name: 'Open menu' }).click()
      await page.getByRole('menuitem', { name: /view details/i }).click()

      await page.getByRole('button', { name: /^edit$/i }).first().click()

      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      await dialog.getByLabel(/description/i).fill('Updated by Playwright')
      await dialog.getByRole('button', { name: /(save|create)/i }).first().click()
      await expect(dialog).toHaveCount(0)

      await expect(page.getByText('Updated by Playwright')).toBeVisible()
    })

    test('deletes the created domain', async ({ page }) => {
      await page.goto('/settings/data-domains')
      const row = page.locator('table >> tbody >> tr', { hasText: domainName })
      await row.getByRole('button', { name: 'Open menu' }).click()
      await page.getByRole('menuitem', { name: /delete domain/i }).click()

      const confirmDialog = page.getByRole('alertdialog').or(page.getByRole('dialog'))
      await expect(confirmDialog).toBeVisible()
      await confirmDialog.getByRole('button', { name: /delete/i }).click()

      await expect(row).toHaveCount(0)
    })
  })
})

// ---------------------------------------------------------------------------
// CUJ-0.1  Teams
// ---------------------------------------------------------------------------
test.describe('CUJ-0.1 — Teams CRUD', () => {
  test('lists existing teams', async ({ page }) => {
    await page.goto('/settings/teams')
    const rows = page.locator('table >> tbody >> tr')
    await expect(rows.first()).toBeVisible()
    expect(await rows.count()).toBeGreaterThan(0)
  })

  test.describe.serial('create and delete team', () => {
    const teamName = `PW Team ${Date.now()}`

    test('creates a new team', async ({ page }) => {
      await page.goto('/settings/teams')
      await page.getByRole('button', { name: /add new team/i }).click()

      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      await dialog.getByLabel(/team name/i).fill(teamName)
      await dialog.getByRole('button', { name: /create team/i }).click()
      await expect(dialog).toHaveCount(0)

      await expect(page.getByText(teamName)).toBeVisible()
    })

    test('deletes the created team', async ({ page }) => {
      await page.goto('/settings/teams')
      const row = page.locator('table >> tbody >> tr', { hasText: teamName })
      await row.getByRole('button', { name: 'Open menu' }).click()
      await page.getByRole('menuitem', { name: /delete team/i }).click()

      const confirmDialog = page.getByRole('alertdialog').or(page.getByRole('dialog'))
      await expect(confirmDialog).toBeVisible()
      await confirmDialog.getByRole('button', { name: /delete/i }).click()

      await expect(row).toHaveCount(0)
    })
  })
})

// ---------------------------------------------------------------------------
// CUJ-0.2  Projects
// ---------------------------------------------------------------------------
test.describe('CUJ-0.2 — Projects CRUD', () => {
  test('lists existing projects', async ({ page }) => {
    await page.goto('/settings/projects')
    const rows = page.locator('table >> tbody >> tr')
    await expect(rows.first()).toBeVisible()
    expect(await rows.count()).toBeGreaterThan(0)
  })

  test.describe.serial('create and delete project', () => {
    const projectName = `PW Project ${Date.now()}`

    test('creates a new project', async ({ page }) => {
      await page.goto('/settings/projects')
      await page.getByRole('button', { name: /add new project/i }).click()

      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()

      await dialog.getByLabel(/project name/i).fill(projectName)
      await dialog.getByRole('button', { name: /create project/i }).click()
      await expect(dialog).toHaveCount(0)

      await expect(page.getByText(projectName)).toBeVisible()
    })

    test('deletes the created project', async ({ page }) => {
      await page.goto('/settings/projects')
      const row = page.locator('table >> tbody >> tr', { hasText: projectName })
      await row.getByRole('button', { name: 'Open menu' }).click()
      await page.getByRole('menuitem', { name: /delete project/i }).click()

      const confirmDialog = page.getByRole('alertdialog').or(page.getByRole('dialog'))
      await expect(confirmDialog).toBeVisible()
      await confirmDialog.getByRole('button', { name: /delete/i }).click()

      await expect(row).toHaveCount(0)
    })
  })
})
