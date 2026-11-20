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

function mockTrend(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(body) }),
  );
}

describe('useComplianceData', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('reads a latest day without a score as "No score", not 0%', async () => {
    mockTrend([
      { date: '2026-11-19', compliance: 80 },
      { date: '2026-11-20', compliance: null },
    ]);
    const { result } = renderHook(() => useComplianceData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.value).toBe('compliance:runScoreCoverage.noScore');
    expect(result.current.customData?.trendData).toEqual([80, null]);
  });

  it('shows the latest score as a percentage', async () => {
    mockTrend([{ date: '2026-11-20', compliance: 75.5 }]);
    const { result } = renderHook(() => useComplianceData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.value).toBe('75.5%');
  });
});
