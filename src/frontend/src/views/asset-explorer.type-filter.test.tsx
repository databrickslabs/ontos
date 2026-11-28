/**
 * Opening the explorer with ?type= (e.g. Back from an asset) lists only that
 * type's assets, even when an all-assets response would arrive late.
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { TooltipProvider } from '@/components/ui/tooltip';

import AssetExplorer from './asset-explorer';

const api = vi.hoisted(() => ({
  get: vi.fn(),
  toast: vi.fn(),
  permissions: { hasPermission: () => true, isLoading: false },
}));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: vi.fn(), put: vi.fn(), delete: vi.fn() }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('@/stores/permissions-store', () => ({ usePermissions: () => api.permissions }));

const SYSTEM = { id: 't-sys', name: 'System', category: 'system', asset_count: 1 };
const TABLE = { id: 't-tab', name: 'Table', category: 'data', asset_count: 1 };
const asset = (id: string, name: string, typeId: string) => ({ id, name, asset_type_id: typeId, status: 'active' });

describe('AssetExplorer type filter from the URL', () => {
  it('lists only the type in the URL and never loads all assets first', async () => {
    api.get.mockImplementation(async (url: string) => {
      if (url === '/api/asset-types') return { data: [SYSTEM, TABLE] };
      if (url.startsWith('/api/assets?')) {
        const typeId = new URLSearchParams(url.split('?')[1]).get('asset_type_id');
        if (typeId === 't-sys') return { data: { items: [asset('a-1', 'AVEVA PI Historian', 't-sys')], total: 1, skip: 0, limit: 10 } };
        // All assets: slower, so it would land last
        await new Promise((r) => setTimeout(r, 50));
        return { data: { items: [asset('a-1', 'AVEVA PI Historian', 't-sys'), asset('a-2', 'analyst_id', 't-tab')], total: 2, skip: 0, limit: 10 } };
      }
      return { data: [] };
    });

    render(
      <TooltipProvider>
        <MemoryRouter initialEntries={['/assets?type=System']}>
          <AssetExplorer />
        </MemoryRouter>
      </TooltipProvider>,
    );

    expect(await screen.findByText('AVEVA PI Historian')).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.queryByText('analyst_id')).toBeNull();
    const assetCalls = api.get.mock.calls.map(([url]) => url as string).filter((u) => u.startsWith('/api/assets?'));
    expect(assetCalls.length).toBeGreaterThan(0);
    expect(assetCalls.every((u) => u.includes('asset_type_id=t-sys'))).toBe(true);
  });
});
