import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { mergeById, useDataProductsData } from './use-data-products-data';

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    hasPermission: () => true,
    appliedRoleId: 'r',
    isLoading: false,
  }),
}));

function mockLists(owned: unknown[], published: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(url.endsWith('/published') ? published : owned),
    })),
  );
}

describe('useDataProductsData', () => {
  afterEach(() => vi.unstubAllGlobals());

  // #1617: a consumer owns no product, so the list endpoint returns none, yet
  // the Marketplace shows the published ones.
  it('counts the published products for a user who owns none', async () => {
    mockLists([], [
      { id: 'a', status: 'active' },
      { id: 'b', status: 'active' },
    ]);
    const { result } = renderHook(() => useDataProductsData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.value).toBe(2);
  });

  it('counts a product that is both owned and published once', async () => {
    mockLists(
      [{ id: 'a', status: 'active' }, { id: 'd', status: 'draft' }],
      [{ id: 'a', status: 'active' }],
    );
    const { result } = renderHook(() => useDataProductsData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.value).toBe(2);
    const breakdown = result.current.customData?.statusBreakdown as Array<{
      status: string; count: number;
    }>;
    expect(breakdown.find((s) => s.status === 'active')?.count).toBe(1);
    expect(breakdown.find((s) => s.status === 'draft')?.count).toBe(1);
  });

  it('reports an error when a list fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 403 }));
    const { result } = renderHook(() => useDataProductsData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.value).toBe(0);
    expect(result.current.error).toBe('HTTP 403');
  });
});

describe('mergeById', () => {
  it('keeps the first copy of each id and skips rows without one', () => {
    expect(mergeById([{ id: 'a', n: 1 }, {}], [{ id: 'a', n: 2 }, { id: 'b' }])).toEqual([
      { id: 'a', n: 1 },
      { id: 'b' },
    ]);
  });
});
