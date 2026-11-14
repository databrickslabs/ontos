/**
 * Settings > Asset Types lists retired types too, marked retired (#970).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const getMock = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: getMock, delete: vi.fn(), loading: false }),
}));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => true, isLoading: false }),
}));
vi.mock('@/components/settings/settings-page-wrapper', () => ({
  default: ({ children }: any) => <div>{children}</div>,
}));
vi.mock('@/components/common/list-view-skeleton', () => ({ ListViewSkeleton: () => null }));
vi.mock('@/components/common/relative-date', () => ({ RelativeDate: () => null }));
vi.mock('@/components/asset-types/asset-type-form-dialog', () => ({ AssetTypeFormDialog: () => null }));
vi.mock('@/components/ui/data-table', () => ({
  DataTable: ({ columns, data }: any) => (
    <div>
      {data.map((row: any) => (
        <div key={row.id} data-testid={`row-${row.name}`}>
          {columns.find((c: any) => c.accessorKey === 'status').cell({ row: { original: row } })}
        </div>
      ))}
    </div>
  ),
}));

import AssetTypesView from './asset-types';

const ACTIVE = {
  id: 'a1', name: 'Table', is_system: true, status: 'active', asset_count: 3,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};
const RETIRED = {
  id: 'r1', name: 'Legacy Business Term', is_system: true, status: 'retired', asset_count: 4,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};

describe('AssetTypesView retired types', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMock.mockImplementation(async (url: string) => (
      url.endsWith('status=retired') ? { data: [RETIRED] } : { data: [ACTIVE] }
    ));
  });

  it('fetches active and retired types and lists both', async () => {
    render(<AssetTypesView />);
    await waitFor(() => expect(screen.getByTestId('row-Legacy Business Term')).toBeTruthy());
    expect(getMock).toHaveBeenCalledWith('/api/asset-types');
    expect(getMock).toHaveBeenCalledWith('/api/asset-types?status=retired');
    expect(screen.getByTestId('row-Table')).toBeTruthy();
  });

  it('marks a retired type with the retired status badge', async () => {
    render(<AssetTypesView />);
    const row = await screen.findByTestId('row-Legacy Business Term');
    expect(row.textContent).toContain('statuses.retired');
    expect(screen.getByTestId('row-Table').textContent).toContain('statuses.active');
  });
});
