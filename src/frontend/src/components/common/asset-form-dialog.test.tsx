import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { AssetRead } from '@/types/asset';

const toastMock = vi.fn();
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: toastMock }) }));

const putMock = vi.fn();
const getMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: getMock, post: vi.fn(), put: putMock }),
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

function renderDialog(props: { asset?: AssetRead; assetTypeIri?: string } = {}) {
  const onSuccess = vi.fn();
  render(
    <AssetFormDialog
      isOpen
      onOpenChange={vi.fn()}
      onSuccess={onSuccess}
      assetTypeId="t1"
      assetTypeName="Table"
      assetTypeIri={props.assetTypeIri}
      asset={props.asset ?? asset}
    />
  );
  return onSuccess;
}

// The ontology's Table schema: Physical Path is required
const tableSchema = {
  type_iri: 'http://ontos.app/ontology#Table',
  type_label: 'Table',
  model_tier: 'physical',
  fields: [{
    iri: 'http://ontos.app/ontology#physicalPath',
    name: 'physicalPath',
    label: 'physical path',
    comment: 'Fully qualified path in the target system',
    range_type: 'string',
    field_type: 'text',
    field_order: 10,
    is_required: true,
    field_group: 'technical',
  }],
};

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
      description: 'main.sales.orders was not found in Unity Catalog, or you don\'t have access ' +
        'to it, so its description was not written there.',
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

describe('AssetFormDialog - Physical Path and Location', () => {
  beforeEach(() => {
    toastMock.mockClear();
    putMock.mockReset();
    getMock.mockReset();
    getMock.mockResolvedValue({ data: tableSchema });
    putMock.mockResolvedValue({ data: { ...asset, warnings: [] } });
  });

  it('saves a table whose Location is set without a separate Physical Path', async () => {
    const onSuccess = renderDialog({ assetTypeIri: tableSchema.type_iri });
    await screen.findByText(/physical path/i);

    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(putMock).toHaveBeenCalledTimes(1);
  });

  it('still requires a path when Location is empty too', async () => {
    const onSuccess = renderDialog({
      assetTypeIri: tableSchema.type_iri, asset: { ...asset, location: null },
    });
    await screen.findByText(/physical path/i);

    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));

    expect(await screen.findByText(/is required/i)).toBeInTheDocument();
    expect(putMock).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
