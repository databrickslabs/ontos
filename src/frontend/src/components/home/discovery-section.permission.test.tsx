/** Popular products need data-products read; without it the card must not call the API. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { FeatureAccessLevel } from '@/types/settings';

const state = vi.hoisted(() => ({ permissions: {} as Record<string, string> }));

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    isLoading: false,
    hasPermission: (id: string, level: string) => {
      const order = ['None', 'Read-only', 'Filtered', 'Read/Write', 'Full', 'Admin'];
      return order.indexOf(state.permissions[id] ?? 'None') >= order.indexOf(level);
    },
  }),
}));

vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({ domains: [], loading: false, getDomainName: () => '' }),
}));

vi.mock('@/hooks/use-approval-wizard-trigger', () => ({
  useApprovalWizardTrigger: () => ({ lookupWorkflowId: vi.fn() }),
}));

import DiscoverySection from './discovery-section';

const calls = (spy: ReturnType<typeof vi.fn>, path: string) =>
  spy.mock.calls.filter(([url]) => String(url).includes(path));

describe('DiscoverySection permissions', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    state.permissions = {};
    fetchSpy = vi.fn(async () => ({ ok: false, status: 403, json: async () => ({}) }));
    globalThis.fetch = fetchSpy as any;
  });

  it('skips published products and hides raw HTTP errors without read', async () => {
    renderWithProviders(<DiscoverySection />);
    expect(await screen.findByText('No data products found.')).toBeTruthy();
    expect(calls(fetchSpy, '/api/data-products/published')).toHaveLength(0);
    expect(screen.queryByText(/HTTP error/)).toBeNull();
  });

  it('calls the API with data-products read and hides the raw status on failure', async () => {
    state.permissions = { 'data-products': FeatureAccessLevel.READ_ONLY };
    renderWithProviders(<DiscoverySection />);
    expect(await screen.findByText('Failed to load data products')).toBeTruthy();
    await waitFor(() => expect(calls(fetchSpy, '/api/data-products/published')).toHaveLength(1));
    expect(screen.queryByText(/HTTP error/)).toBeNull();
  });
});
