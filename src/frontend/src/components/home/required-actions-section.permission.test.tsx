/** The approvals queue needs data-contracts read; without it the section must not call it. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { FeatureAccessLevel } from '@/types/settings';

const state = vi.hoisted(() => ({
  permissions: {} as Record<string, string>,
  permissionsLoading: false,
}));

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    isLoading: state.permissionsLoading,
    hasPermission: (id: string, level: string) => {
      const order = ['None', 'Read-only', 'Filtered', 'Read/Write', 'Full', 'Admin'];
      return order.indexOf(state.permissions[id] ?? 'None') >= order.indexOf(level);
    },
  }),
}));

vi.mock('@/stores/notifications-store', () => ({
  useNotificationsStore: () => ({
    notifications: [],
    isLoading: false,
    fetchNotifications: vi.fn(),
    markAsRead: vi.fn(),
  }),
}));

import RequiredActionsSection from './required-actions-section';

const queueCalls = (spy: ReturnType<typeof vi.fn>) =>
  spy.mock.calls.filter(([url]) => String(url).includes('/api/approvals/queue'));

describe('RequiredActionsSection permissions', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    state.permissionsLoading = false;
    state.permissions = {};
    fetchSpy = vi.fn(async () => ({
      ok: false,
      status: 403,
      json: async () => ({ detail: 'forbidden' }),
    }));
    globalThis.fetch = fetchSpy as any;
  });

  it('does not call the queue nor show a raw HTTP error without data-contracts read', async () => {
    renderWithProviders(<RequiredActionsSection />);
    await waitFor(() => expect(screen.queryByText(/HTTP 403/)).toBeNull());
    expect(queueCalls(fetchSpy)).toHaveLength(0);
    expect(await screen.findByText('No pending actions.')).toBeTruthy();
  });

  it('calls the queue with data-contracts read and hides the raw status on failure', async () => {
    state.permissions = { 'data-contracts': FeatureAccessLevel.READ_ONLY };
    fetchSpy.mockImplementation(async () => ({ ok: false, status: 500, json: async () => ({}) }));
    renderWithProviders(<RequiredActionsSection />);
    expect(await screen.findByText('Failed to load approvals')).toBeTruthy();
    expect(queueCalls(fetchSpy)).toHaveLength(1);
    expect(screen.queryByText(/HTTP 500/)).toBeNull();
  });
});
