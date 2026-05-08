/**
 * Component tests for AssetSelector — focused on the `targetAssetTypes`
 * filter.
 *
 * Regression target: the "Link Asset" picker on Data Product output ports
 * was previously showing every asset type including Catalog and Schema.
 * Submitting either yielded a 422 from the backend ontology validator.
 * The fix narrows the picker via `targetAssetTypes`; these tests assert that
 * filter is honoured in Browse mode (where the type sidebar is rendered).
 */
import { screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { AssetSelector } from './asset-selector';

// Mock the asset-types endpoint so Browse mode has a deterministic list.
const mockAssetTypes = [
  { id: '1', name: 'Table', category: 'data', status: 'active', asset_count: 10, icon: 'Table2' },
  { id: '2', name: 'View', category: 'data', status: 'active', asset_count: 5, icon: 'Eye' },
  { id: '3', name: 'Dataset', category: 'data', status: 'active', asset_count: 3, icon: 'Database' },
  { id: '4', name: 'APIEndpoint', category: 'integration', status: 'active', asset_count: 2, icon: 'Globe' },
  { id: '5', name: 'MLModel', category: 'analytics', status: 'active', asset_count: 1, icon: 'Brain' },
  { id: '6', name: 'Catalog', category: 'system', status: 'active', asset_count: 4, icon: 'FolderOpen' },
  { id: '7', name: 'Schema', category: 'system', status: 'active', asset_count: 8, icon: 'FolderOpen' },
];

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    get: vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/asset-types')) {
        return Promise.resolve({ data: mockAssetTypes, error: null });
      }
      return Promise.resolve({ data: { items: [], total: 0 }, error: null });
    }),
  }),
}));

describe('AssetSelector targetAssetTypes filter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders all active asset types in Browse mode when no filter is set', async () => {
    renderWithProviders(
      <AssetSelector
        isOpen={true}
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
      />
    );

    // Wait for the asset-types API to resolve and the sidebar to render.
    await waitFor(() => expect(screen.getByText('Table')).toBeInTheDocument());

    // Container types are visible — backward compatibility for callers that
    // don't pass `targetAssetTypes`.
    expect(screen.getByText('Catalog')).toBeInTheDocument();
    expect(screen.getByText('Schema')).toBeInTheDocument();
    expect(screen.getByText('Table')).toBeInTheDocument();
    expect(screen.getByText('View')).toBeInTheDocument();
  });

  it('hides asset types not in targetAssetTypes (output-port deliverables only)', async () => {
    const deliverableTypes = ['Table', 'View', 'Dataset', 'APIEndpoint', 'MLModel'];

    renderWithProviders(
      <AssetSelector
        isOpen={true}
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
        targetAssetTypes={deliverableTypes}
      />
    );

    await waitFor(() => expect(screen.getByText('Table')).toBeInTheDocument());

    // Deliverable types are visible.
    expect(screen.getByText('Table')).toBeInTheDocument();
    expect(screen.getByText('View')).toBeInTheDocument();
    expect(screen.getByText('Dataset')).toBeInTheDocument();
    expect(screen.getByText('APIEndpoint')).toBeInTheDocument();
    expect(screen.getByText('MLModel')).toBeInTheDocument();

    // Container types — the original 422 trigger — must NOT be in the picker.
    expect(screen.queryByText('Catalog')).not.toBeInTheDocument();
    expect(screen.queryByText('Schema')).not.toBeInTheDocument();
  });

  it('renders the caller-supplied helper text in the dialog description', async () => {
    const helperText =
      'Only deliverable asset types (Table, View, Dataset, API Endpoint, ML Model) can be linked to an output port.';

    renderWithProviders(
      <AssetSelector
        isOpen={true}
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
        targetAssetTypes={['Table', 'View', 'Dataset', 'APIEndpoint', 'MLModel']}
        description={helperText}
      />
    );

    expect(screen.getByText(helperText)).toBeInTheDocument();
  });
});
