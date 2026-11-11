import { test, expect, APIRequestContext, Page } from '@playwright/test'
import { loadDemoData, dismissCopilot } from './helpers/demo-data'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

/**
 * A request that goes through an approval wizard (here: product publish) is
 * sent when the wizard completes, not when it is closed. Leaving the page on
 * the completion screen (reload, browser back) used to lose the request.
 */

async function activeProductId(request: APIRequestContext): Promise<string> {
  const resp = await request.get(`${BACKEND_URL}/api/data-products`)
  const body = await resp.json()
  const products = Array.isArray(body) ? body : body.items ?? body.data_products ?? []
  const product = products.find((p: { status?: string }) => (p.status || '').toLowerCase() === 'active')
  expect(product, 'an active demo data product').toBeTruthy()
  return product.id
}

async function completePublishWizard(page: Page, productId: string) {
  await page.goto(`/data-products/${productId}`)
  await page.getByRole('button', { name: /^Request/ }).first().click()
  const dialog = page.locator('[role="dialog"]').last()
  await dialog.locator('button[role="combobox"]').first().click()
  await page.getByRole('option', { name: /Request Publish/i }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
  const wizard = page.locator('[role="dialog"]').last()
  const reason = wizard.locator('textarea, input[type="text"]').first()
  await reason.fill('Publish for the reporting consumers')
  await wizard.getByRole('button', { name: 'Complete' }).click()
}

test.beforeAll(async ({ request }) => {
  await loadDemoData(request)
  // The publish request wizard (for_request_publish) is a default workflow
  const resp = await request.post(`${BACKEND_URL}/api/workflows/load-defaults?update_existing=false`)
  expect(resp.ok()).toBeTruthy()
  // Default workflows are created inactive; the dialog only runs the wizard
  // when it is active
  const list = await (await request.get(`${BACKEND_URL}/api/workflows`)).json()
  const workflows: { id: string; is_active: boolean; trigger?: { type?: string } }[] =
    Array.isArray(list) ? list : list.workflows ?? []
  const wizard = workflows.find((w) => w.trigger?.type === 'for_request_publish')
  expect(wizard, 'the default publish request wizard').toBeTruthy()
  if (!wizard!.is_active) {
    const toggled = await request.post(
      `${BACKEND_URL}/api/workflows/${wizard!.id}/toggle-active?is_active=true`,
    )
    expect(toggled.ok()).toBeTruthy()
  }
})

test.describe('Approval wizard request submit', () => {
  test.beforeEach(async ({ page }) => {
    await dismissCopilot(page)
  })

  test('sends the request when the wizard completes, and only once', async ({ page, request }) => {
    const productId = await activeProductId(request)
    const sent: number[] = []
    page.on('response', (r) => {
      if (r.url().includes(`/api/data-products/${productId}/request-publish`) && r.request().method() === 'POST') {
        sent.push(r.status())
      }
    })

    await completePublishWizard(page, productId)

    // Sent while the completion screen is still showing
    await expect(page.getByText('Agreement recorded')).toBeVisible()
    await expect.poll(() => sent).toEqual([202])
    await expect(page.getByText('Request Submitted').first()).toBeVisible()

    // Closing the wizard doesn't send it again
    // By test id: the button's accessible name is translated.
    await page.locator('[role="dialog"]').last().getByTestId('dialog-close').first().click()
    await expect(page.locator('[role="dialog"]')).toHaveCount(0)
    await page.waitForTimeout(1000)
    expect(sent).toEqual([202])
  })

  test('a reload on the completion screen keeps the request', async ({ page, request }) => {
    const productId = await activeProductId(request)
    let sent = 0
    page.on('request', (r) => {
      if (r.url().includes(`/api/data-products/${productId}/request-publish`) && r.method() === 'POST') sent++
    })

    await completePublishWizard(page, productId)
    await expect(page.getByText('Agreement recorded')).toBeVisible()
    await expect.poll(() => sent).toBe(1)

    await page.reload()
    await page.waitForLoadState('networkidle')
    expect(sent).toBe(1)
  })
})
