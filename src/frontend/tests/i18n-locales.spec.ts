import { test, expect, Page } from '@playwright/test';

/**
 * Cross-locale coverage (issue #471).
 *
 * Switches through all 7 supported locales, visits the main navigation routes,
 * and smoke-tests that:
 *   - the route renders (a heading is visible), and
 *   - no visible text leaks an untranslated marker (`__TODO__`) or a raw i18n
 *     key path (e.g. `data-products.title` rendered literally).
 *
 * Requires the app to be running (see playwright.config webServer / BASE_URL).
 */

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'ja', 'nl'] as const;

const ROUTES = [
  '/',
  '/data-products',
  '/data-contracts',
  '/settings',
  '/compliance',
  '/catalog-commander',
] as const;

// A run of 3+ dot-separated lowercase-ish segments is almost certainly an
// i18n key path that was rendered because it was missing everywhere.
const RAW_KEY_RE = /\b[a-z][a-zA-Z0-9]*(?:\.[a-z][a-zA-Z0-9]+){2,}\b/;

async function setLocale(page: Page, locale: string) {
  await page.addInitScript((lng) => {
    window.localStorage.setItem('i18nextLng', lng);
  }, locale);
}

test.describe('i18n locale coverage', () => {
  for (const locale of LOCALES) {
    test(`renders main routes with no leaked keys/markers [${locale}]`, async ({ page }) => {
      await setLocale(page, locale);

      for (const route of ROUTES) {
        await page.goto(route);
        await page.waitForLoadState('networkidle');

        // Route renders something meaningful.
        await expect(page.locator('h1, h2, [role="heading"]').first()).toBeVisible({
          timeout: 10_000,
        });

        const bodyText = (await page.locator('main, body').first().innerText()) || '';

        // No untranslated markers should reach the UI.
        expect(bodyText, `__TODO__ marker visible on ${route} [${locale}]`).not.toContain(
          '__TODO__',
        );

        // No raw key paths should render as visible copy.
        const leaked = bodyText
          .split('\n')
          .map((l) => l.trim())
          .find((l) => l.length > 0 && RAW_KEY_RE.test(l) && !l.includes(' '));
        expect(leaked, `raw i18n key visible on ${route} [${locale}]: ${leaked}`).toBeFalsy();
      }
    });
  }
});
