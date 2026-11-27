import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DescriptionDriftNotice } from './description-drift-notice';

const getMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: getMock, post: vi.fn() }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));

const field = (over = {}) => ({
  asset_id: 't', name: 'orders', object_type: 'table', target: 'main.sales.orders',
  description: 'a', uc_comment: 'b', baseline_known: true, baseline_text: 'a',
  differs: true, changed_in_uc: false, missing_in_uc: false, ...over,
});

const drift = (fields: unknown[]) => ({
  asset_id: 't', target: 'main.sales.orders', fields, truncated: false,
});

function renderNotice(props = {}) {
  render(
    <DescriptionDriftNotice
      assetId="t" assetTypeName="Table" enabled onReset={vi.fn()} {...props}
    />
  );
}

describe('DescriptionDriftNotice', () => {
  beforeEach(() => getMock.mockReset());

  it('says the comment changed in Unity Catalog since Ontos last saw it', async () => {
    getMock.mockResolvedValue({ data: drift([field({ changed_in_uc: true })]) });
    renderNotice();

    expect(await screen.findByText('Changed in Unity Catalog')).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledTimes(1);
    expect(getMock).toHaveBeenCalledWith('/api/assets/t/description/drift');
  });

  it('shows no badge once the Ontos text matches the new comment', async () => {
    getMock.mockResolvedValue({
      data: drift([field({ changed_in_uc: true, differs: false }),
        field({ asset_id: 'c1', changed_in_uc: true, differs: false })]),
    });
    renderNotice();

    expect(await screen.findByRole('button', { name: 'Compare with Unity Catalog' }))
      .toBeInTheDocument();
    expect(screen.queryByText(/Changed in Unity Catalog/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Columns changed/)).not.toBeInTheDocument();
  });

  it('counts the columns that changed', async () => {
    getMock.mockResolvedValue({
      data: drift([field(), field({ asset_id: 'c1', changed_in_uc: true }),
        field({ asset_id: 'c2', changed_in_uc: true })]),
    });
    renderNotice();

    expect(await screen.findByText('Columns changed in Unity Catalog: 2')).toBeInTheDocument();
    expect(screen.queryByText('Changed in Unity Catalog')).not.toBeInTheDocument();
  });

  it('shows no badge when nothing changed, but still offers the comparison', async () => {
    getMock.mockResolvedValue({ data: drift([field()]) });
    renderNotice();

    expect(await screen.findByRole('button', { name: 'Compare with Unity Catalog' }))
      .toBeInTheDocument();
    expect(screen.queryByText(/Changed in Unity Catalog/)).not.toBeInTheDocument();
  });

  it('opens the comparison', async () => {
    getMock.mockResolvedValue({ data: drift([field()]) });
    renderNotice();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Compare with Unity Catalog' })
    );

    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('offers no comparison for a column', async () => {
    getMock.mockResolvedValue({ data: drift([field({ object_type: 'column' })]) });
    renderNotice({ assetTypeName: 'Column' });

    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /Compare/ })).not.toBeInTheDocument();
  });

  it('shows nothing when Unity Catalog could not be read', async () => {
    getMock.mockResolvedValue({ data: null, error: 'no token', errorCode: 'user_token_required' });
    renderNotice();

    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(screen.queryByTestId('description-drift')).not.toBeInTheDocument();
  });

  it('does not read Unity Catalog when it does not apply', () => {
    renderNotice({ enabled: false });

    expect(getMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId('description-drift')).not.toBeInTheDocument();
  });
});
