/**
 * Tier 3 visibility matrix — UI list assertions + screenshots.
 *
 * Prerequisites:
 *   - Frontend on http://localhost:3000 with VITE_TEST_USER_TOKEN set
 *   - Backend on http://localhost:8000 with TEST_USER_TOKEN set
 *   - Matrix seed applied (Tier 2 fixture or manual)
 *
 * Run from repo root:
 *   cd tests/e2e/playwright && npx playwright test
 *
 * Typecheck only:
 *   npx tsc --noEmit visibility_matrix.spec.ts
 */
import { test, expect } from '@playwright/test';
import * as path from 'path';

const EVIDENCE_DIR = path.join(
  __dirname,
  '../../../docs/visibility-rules-evidence',
);

const PERSONA_LABELS: Record<string, string> = {
  producer_a: 'Matrix: Producer (Team A)',
  consumer_b: 'Matrix: Consumer (Team B)',
  admin_ws: 'Matrix: Workspace admin',
  outsider: 'Matrix: Outsider',
};

type EntitySpec = {
  entity: string;
  route: string;
  rowName: string;
  persona: string;
  expectVisible: boolean;
  deviationId?: string;
};

const ENTITY_SPECS: EntitySpec[] = [
  {
    entity: 'data_product',
    route: '/data-products',
    rowName: 'matrix-dp-p1',
    persona: 'producer_a',
    expectVisible: true,
  },
  {
    entity: 'data_product',
    route: '/data-products',
    rowName: 'matrix-dp-p1',
    persona: 'consumer_b',
    expectVisible: false,
  },
  {
    entity: 'data_contract',
    route: '/data-contracts',
    rowName: 'matrix-dc-p2',
    persona: 'producer_a',
    expectVisible: false,
    deviationId: 'DC1',
  },
  {
    entity: 'asset_review',
    route: '/data-asset-reviews',
    rowName: 'matrix-ar',
    persona: 'producer_a',
    expectVisible: false,
    deviationId: 'AR1',
  },
  {
    entity: 'asset',
    route: '/assets',
    rowName: 'matrix',
    persona: 'producer_a',
    expectVisible: true,
    deviationId: 'AS1',
  },
  {
    entity: 'glossary',
    route: '/business-glossary',
    rowName: 'matrix-glossary',
    persona: 'outsider',
    expectVisible: false,
    deviationId: 'GL1',
  },
  {
    entity: 'project',
    route: '/projects',
    rowName: 'matrix-project-p1',
    persona: 'producer_a',
    expectVisible: true,
  },
  {
    entity: 'team',
    route: '/teams',
    rowName: 'matrix-team-a',
    persona: 'producer_a',
    expectVisible: true,
  },
  {
    entity: 'comment',
    route: '/data-products',
    rowName: 'matrix-dp-p1',
    persona: 'producer_a',
    expectVisible: true,
  },
  {
    entity: 'mdm',
    route: '/master-data',
    rowName: 'matrix-mdm',
    persona: 'producer_a',
    expectVisible: false,
    deviationId: 'MD1',
  },
];

async function selectPersona(page: import('@playwright/test').Page, persona: string) {
  const label = PERSONA_LABELS[persona];
  if (!label) return;
  await page.getByRole('button', { name: /user|account|profile/i }).first().click({ timeout: 5000 }).catch(() => {});
  await page.getByText(label, { exact: false }).click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(500);
}

for (const spec of ENTITY_SPECS) {
  const title = `${spec.entity} — ${spec.persona}${spec.deviationId ? ` (${spec.deviationId})` : ''}`;

  const run = spec.deviationId
    ? test.fail
    : test;

  run(title, async ({ page }) => {
    await page.goto(spec.route);
    await selectPersona(page, spec.persona);
    await page.reload();
    await page.waitForLoadState('networkidle');

    const row = page.getByText(spec.rowName, { exact: false });
    if (spec.expectVisible) {
      await expect(row.first()).toBeVisible({ timeout: 15_000 });
    } else {
      await expect(row).toHaveCount(0, { timeout: 10_000 });
    }

    await page.screenshot({
      path: path.join(EVIDENCE_DIR, `${spec.entity}__${spec.persona}.png`),
      fullPage: true,
    });
  });
}
