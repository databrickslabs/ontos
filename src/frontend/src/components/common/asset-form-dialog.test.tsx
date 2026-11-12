import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { AssetRead } from '@/types/asset';

const toastMock = vi.fn();
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: toastMock }) }));

const putMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: vi.fn(), post: vi.fn(), put: putMock }),
}));

vi.mock('@/components/ui/domain-multi-selector', () => ({ default: () => null }));

import { AssetFormDialog } from './asset-form-dialog';

const asset: AssetRead = {
  id: 'a1',
  name: 'orders',
  description: 'Old text',
  asset_type_id: 't1',
  asset_type_name: 'Table',
  platform: 'databricks',
  location: 'main.sales.orders',
  status: 'active',
  relationships: [],
  created_at: '2026-11-12T00:00:00Z',
  updated_at: '2026-11-12T00:00:00Z',
};

function renderDialog() {
  const onSuccess = vi.fn();
  render(
    <AssetFormDialog
      isOpen
      onOpenChange={vi.fn()}
      onSuccess={onSuccess}
      assetTypeId="t1"
      assetTypeName="Table"
      asset={asset}
    />
  );
  return onSuccess;
}

describe('AssetFormDialog - Unity Catalog description warning', () => {
  beforeEach(() => {
    toastMock.mockClear();
    putMock.mockReset();
  });

  it('shows the translated warning when Unity Catalog is not updated', async () => {
    putMock.mockResolvedValue({
      data: {
        ...asset,
        warnings: [{
          code: 'uc_description_object_not_found',
          message: 'english fallback',
          params: { object: 'main.sales.orders' },
        }],
      },
    });
    const onSuccess = renderDialog();

    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(toastMock).toHaveBeenCalledTimes(1);
    expect(toastMock).toHaveBeenCalledWith({
      title: 'Saved in Ontos, not in Unity Catalog',
      description: 'main.sales.orders was not found in Unity Catalog.',
    });
  });

  it('shows the usual confirmation without warnings', async () => {
    putMock.mockResolvedValue({ data: { ...asset, warnings: [] } });
    const onSuccess = renderDialog();

    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(toastMock).toHaveBeenCalledTimes(1);
    expect(toastMock.mock.calls[0][0].title).not.toMatch(/Unity Catalog/);
  });
});
