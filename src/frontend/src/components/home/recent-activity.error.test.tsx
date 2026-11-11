/** A failed change-log call shows the translated error, not the HTTP status. */
import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';

const permissions = vi.hoisted(() => ({ isLoading: false, hasPermission: () => true }));

vi.mock('@/stores/permissions-store', () => ({ usePermissions: () => permissions }));

import RecentActivity from './recent-activity';

describe('RecentActivity error', () => {
  it('shows the translated error on 500', async () => {
    globalThis.fetch = vi.fn(async () => (
      { ok: false, status: 500, json: async () => ({}) }
    )) as any;
    renderWithProviders(<RecentActivity />);
    expect(await screen.findByText('Failed to load recent activity')).toBeTruthy();
    expect(screen.queryByText(/HTTP/)).toBeNull();
  });
});
