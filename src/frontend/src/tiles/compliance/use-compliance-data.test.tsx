import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useComplianceData } from './use-compliance-data';

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    hasPermission: () => true,
    appliedRoleId: 'r',
    isLoading: false,
  }),
}));

const { mockT } = vi.hoisted(() => ({ mockT: (key: string) => key }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}));

function mockApi(stats: unknown, trend: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(url.includes('/trend') ? trend : { policies: [], stats }),
    })),
  );
}

describe('useComplianceData', () => {
  afterEach(() => vi.unstubAllGlobals());

  // #1617: the tile showed the latest trend day (often a day without runs)
  // while the Compliance page shows the overall score of the policies.
  it('shows the overall score of the Compliance page, not the latest trend day', async () => {
    mockApi(
      { overall_compliance: 58.102, active_policies: 15, critical_issues: 2 },
      [
        { date: '2026-11-19', compliance: 80 },
        { date: '2026-11-20', compliance: null },
      ],
    );
    const { result } = renderHook(() => useComplianceData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.value).toBe('58%');
    expect(result.current.customData?.trendData).toEqual([80, null]);
  });

  it('reads policies without a score as "No score", not 0%', async () => {
    mockApi(
      { overall_compliance: null, active_policies: 3, critical_issues: 0 },
      [{ date: '2026-11-20', compliance: null }],
    );
    const { result } = renderHook(() => useComplianceData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.value).toBe('compliance:runScoreCoverage.noScore');
  });

  it('is not available without policies or runs', async () => {
    mockApi({ overall_compliance: null, active_policies: 0, critical_issues: 0 }, []);
    const { result } = renderHook(() => useComplianceData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.value).toBe('home:overview.tiles.compliance.notAvailable');
  });

  it('shows not available when a request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    const { result } = renderHook(() => useComplianceData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.value).toBe('home:overview.tiles.compliance.notAvailable');
    expect(result.current.error).toBe('HTTP 500');
  });
});
