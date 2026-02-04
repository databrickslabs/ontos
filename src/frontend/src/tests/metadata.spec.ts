import { test, expect } from '@playwright/test';

test.describe('Data Product Metadata', () => {
  test('documents table shows uploaded docs', async ({ page }) => {
    await page.goto('/data-products/retail-customer-recs-v1');

    await expect(page.getByRole('heading', { name: 'Ports' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Metadata' })).toBeVisible();

    const docsSection = page.getByText('Attached Documents');
    await expect(docsSection).toBeVisible();

    // Table rows under Attached Documents
    const table = docsSection.locator('xpath=..').locator('table');
    await expect(table).toBeVisible();
    const rows = table.locator('tbody tr');
    const count = await rows.count();
    expect(count).toBeGreaterThan(0);
  });
});


