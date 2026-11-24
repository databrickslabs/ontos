/**
 * The asset page keeps the comparison dialog open when a partly failed reset refreshes the
 * asset: the refresh is a background one, not the page-level spinner that unmounts the dialog,
 * so the user still reads which descriptions could not be reset.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const get = vi.fn();
const post = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get, post, put: vi.fn(), delete: vi.fn() }),
}));
vi.mock('@/stores/permissions-store', async (orig) => {
  const actual = await orig<Record<string, unknown>>();
  return {
    ...actual,
    usePermissions: () => ({ hasPermission: () => true, isLoading: false }),
  };
});

// Heavy children fetch their own data and are irrelevant here.
const { Stub } = vi.hoisted(() => ({ Stub: () => null }));
vi.mock('@/components/assets/asset-delete-dialog', () => ({ AssetDeleteDialog: Stub }));
vi.mock('@/components/common/asset-form-dialog', () => ({ AssetFormDialog: Stub }));
vi.mock('@/components/common/business-lineage-graph', () => ({ BusinessLineageGraph: Stub }));
vi.mock('@/components/common/impact-analysis-panel', () => ({ ImpactAnalysisPanel: Stub }));
vi.mock('@/components/lineage', () => ({ BusinessLineageView: Stub }));
vi.mock('@/components/common/lineage-editor', () => ({ LineageEditor: Stub }));
vi.mock('@/components/data-products/maturity-panel', () => ({ MaturityPanel: Stub }));
vi.mock('@/components/common/entity-tree-panel', () => ({ EntityTreePanel: Stub }));
vi.mock('@/components/common/ownership-panel', () => ({ OwnershipPanel: Stub }));
vi.mock('@/components/comments', () => ({ CommentSidebar: Stub }));
vi.mock('@/components/ratings', () => ({ RatingPanel: Stub }));
vi.mock('@/components/metadata/entity-metadata-panel', () => ({ default: Stub }));
vi.mock('@/components/quality/entity-quality-panel', () => ({ default: Stub }));
vi.mock('@/components/semantic/concept-select-dialog', () => ({ default: Stub }));
vi.mock('@/components/semantic/linked-concept-chips', () => ({ default: Stub }));
vi.mock('@/components/assets/asset-metric-view-card', () => ({
  default: Stub, mayBeMetricView: () => false,
}));

import AssetDetailView from './asset-detail';

const ASSET = '/api/assets/a1';

const asset = (updatedAt: string) => ({
  id: 'a1', name: 'orders', description: 'Orders (Ontos)', asset_type_id: 'tt',
  asset_type_name: 'Table', platform: 'databricks', location: 'main.sales.orders',
  status: 'active', created_at: '2026-11-01T10:00:00Z', updated_at: updatedAt,
  properties: null, tags: [], domains: [],
});

const field = (id: string, name: string) => ({
  asset_id: id, name, object_type: id === 'a1' ? 'table' : 'column',
  target: `main.sales.orders${id === 'a1' ? '' : `.${name}`}`,
  description: `${name} (Ontos)`, uc_comment: `${name} (UC)`, baseline_known: true,
  baseline_text: `${name} (UC)`, differs: true, changed_in_uc: false, missing_in_uc: false,
});

const drift = {
  asset_id: 'a1', target: 'main.sales.orders', table_type: 'MANAGED', truncated: false,
  fields: [field('a1', 'orders'), field('c1', 'order_id')],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/assets/a1']}>
      <Routes>
        <Route path="/assets/:assetId" element={<AssetDetailView />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('AssetDetailView description comparison', () => {
  let updatedAt = '2026-11-20T10:00:00Z';

  beforeEach(() => {
    updatedAt = '2026-11-20T10:00:00Z';
    get.mockReset();
    post.mockReset();
    get.mockImplementation(async (url: string) => {
      if (url === ASSET) return { data: asset(updatedAt) };
      if (url === `${ASSET}/description/drift`) return { data: drift };
      if (url.startsWith(`${ASSET}/description/history`)) {
        return { data: { asset_id: 'a1', total: 0, items: [] } };
      }
      if (url.startsWith('/api/semantic-links')) return { data: [] };
      return { data: {} };
    });
    post.mockImplementation(async () => {
      updatedAt = '2026-11-20T11:00:00Z'; // the reset that went through changes the asset
      return {
        data: {
          results: [
            { asset_id: 'a1', changed: true, warnings: [] },
            {
              asset_id: 'c1', changed: false, warnings: [],
              error: { code: 'uc_reset_uc_changed', message: 'english', params: { object: 'x' } },
            },
          ],
          changed: 1, failed: 1,
        },
      };
    });
  });

  it('keeps the dialog and its failure list while the asset is refreshed', async () => {
    renderPage();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Compare with Unity Catalog' })
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Select all' }));
    const assetReads = () => get.mock.calls.filter(([url]) => url === ASSET).length;
    const before = assetReads();

    await userEvent.click(within(dialog).getByRole('button', { name: 'Reset selected (2)' }));

    await waitFor(() => expect(assetReads()).toBe(before + 1));
    const stillOpen = await screen.findByRole('dialog');
    expect(within(stillOpen).getByText(/changed since you looked at it/)).toBeInTheDocument();
    expect(within(stillOpen).getByText('order_id', { selector: 'span.font-medium' }))
      .toBeInTheDocument();
    // The page itself was not replaced by its loading skeleton (behind a modal dialog its
    // elements are hidden from the accessibility tree, so look at the DOM)
    expect(document.querySelector('h1')).toHaveTextContent('orders');
  });
});
