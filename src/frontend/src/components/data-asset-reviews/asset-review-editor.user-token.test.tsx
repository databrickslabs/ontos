/**
 * The editor reads an asset's content as the user. Without the user's token
 * the API refuses with `user_token_required`, and the editor shows that in the
 * user's language instead of the raw JSON or an English prefix.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import i18n from '@/i18n/config';
import AssetReviewEditor from './asset-review-editor';
import { AssetType, ReviewedAsset, ReviewedAssetStatus } from '@/types/data-asset-review';

const ENGLISH = "This request needs the user's Databricks token, and it has none.";
const refused = { detail: { code: 'user_token_required', message: ENGLISH, params: {} } };

const asset = (asset_fqn: string, asset_type: AssetType): ReviewedAsset => ({
  id: 'a-1', asset_fqn, asset_type, status: ReviewedAssetStatus.PENDING,
  updated_at: new Date().toISOString(),
});

function renderEditor(reviewed: ReviewedAsset, get: ReturnType<typeof vi.fn>) {
  const api = { get, post: vi.fn(), put: vi.fn(), delete: vi.fn() } as any;
  render(
    <MemoryRouter>
      <AssetReviewEditor requestId="r-1" asset={reviewed} api={api} onReviewSave={vi.fn()} />
    </MemoryRouter>,
  );
}

describe('AssetReviewEditor without the user token', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('pt');
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
    vi.restoreAllMocks();
  });

  it('shows a refused table preview in the user language, without a prefix', async () => {
    const portuguese = i18n.t('errors:userTokenRequired');
    const get = vi.fn().mockImplementation(async (url: string) => (
      url.includes('/preview')
        ? { data: {}, error: portuguese, errorCode: 'user_token_required' }
        : { data: { enabled: false }, error: null }
    ));
    renderEditor(asset('main.sales.orders', AssetType.TABLE), get);

    expect((await screen.findAllByText(portuguese)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/fetch failed/)).toBeNull();
  });

  it('shows a refused view definition in the user language, not the JSON body', async () => {
    const portuguese = i18n.t('errors:userTokenRequired');
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 403,
      text: async () => JSON.stringify(refused),
    } as Response);
    const get = vi.fn().mockResolvedValue({ data: { enabled: false }, error: null });
    renderEditor(asset('main.sales.v_orders', AssetType.VIEW), get);

    expect((await screen.findAllByText(portuguese)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/user_token_required/)).toBeNull();
  });
});
