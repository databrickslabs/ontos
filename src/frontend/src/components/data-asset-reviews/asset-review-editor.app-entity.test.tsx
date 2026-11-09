/**
 * A data product or contract under review (#174) is stored as
 * `product:<id>` / `contract:<id>` with its own type: the editor links to its
 * page instead of fetching a table preview, which such an FQN doesn't have.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AssetReviewEditor from './asset-review-editor';
import { appEntityAssetLink } from '@/lib/app-entity-asset';
import { AssetType, ReviewedAsset, ReviewedAssetStatus } from '@/types/data-asset-review';

const asset = (asset_fqn: string, asset_type: AssetType): ReviewedAsset => ({
  id: 'a-1', asset_fqn, asset_type, status: ReviewedAssetStatus.PENDING,
  updated_at: new Date().toISOString(),
});

function renderEditor(reviewed: ReviewedAsset) {
  const get = vi.fn().mockResolvedValue({ data: { enabled: false }, error: null });
  const api = { get, post: vi.fn(), put: vi.fn(), delete: vi.fn() } as any;
  render(
    <MemoryRouter>
      <AssetReviewEditor requestId="r-1" asset={reviewed} api={api} onReviewSave={vi.fn()} />
    </MemoryRouter>,
  );
  return get;
}

describe('AssetReviewEditor for app entities', () => {
  it('links a data product to its page and fetches no table preview', async () => {
    const get = renderEditor(asset('product:p-42', AssetType.DATA_PRODUCT));

    const link = await screen.findByRole('link', { name: 'Open data product' });
    expect(link).toHaveAttribute('href', '/data-products/p-42');
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(get.mock.calls.map((c) => c[0])).not.toContainEqual(expect.stringContaining('/preview'));
  });

  it('links a data contract to its page', async () => {
    renderEditor(asset('contract:c-7', AssetType.DATA_CONTRACT));

    const link = await screen.findByRole('link', { name: 'Open data contract' });
    expect(link).toHaveAttribute('href', '/data-contracts/c-7');
  });
});

describe('appEntityAssetLink', () => {
  it('gives the page of products and contracts only', () => {
    expect(appEntityAssetLink(asset('product:p 1', AssetType.DATA_PRODUCT))).toBe('/data-products/p%201');
    expect(appEntityAssetLink(asset('contract:c-1', AssetType.DATA_CONTRACT))).toBe('/data-contracts/c-1');
    // A stored review from before #174: a product named in a table asset
    expect(appEntityAssetLink(asset('product:AML', AssetType.TABLE))).toBeNull();
    expect(appEntityAssetLink(asset('main.sales.orders', AssetType.TABLE))).toBeNull();
    expect(appEntityAssetLink(asset('product:', AssetType.DATA_PRODUCT))).toBeNull();
  });
});
