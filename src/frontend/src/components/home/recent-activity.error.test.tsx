/**
 * The change log decides access (a 403 is an empty card, other failures show the translated
 * error), not the client-side permissions, which miss team role overrides.
 */
import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';

// The permissions store, without team role overrides, says no audit read
const permissions = vi.hoisted(() => ({ isLoading: true, hasPermission: () => false }));

vi.mock('@/stores/permissions-store', () => ({ usePermissions: () => permissions }));

import RecentActivity from './recent-activity';

const answer = (status: number, body: unknown = {}) => ({
  ok: status < 400,
  status,
  json: async () => body,
});

describe('RecentActivity', () => {
  it('shows the translated error on 500', async () => {
    globalThis.fetch = vi.fn(async () => answer(500)) as any;
    renderWithProviders(<RecentActivity />);
    expect(await screen.findByText('Failed to load recent activity')).toBeTruthy();
    expect(screen.queryByText(/HTTP/)).toBeNull();
  });

  it('shows the empty state, not an error, on 403', async () => {
    globalThis.fetch = vi.fn(async () => answer(403, { detail: 'forbidden' })) as any;
    const { container } = renderWithProviders(<RecentActivity />);
    expect(await screen.findByText('No recent activity.')).toBeTruthy();
    expect(screen.queryByText(/HTTP/)).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(globalThis.fetch).toHaveBeenCalled();
  });

  it('loads the change log even when the client-side permissions say no', async () => {
    globalThis.fetch = vi.fn(async () => answer(200, [
      { id: 'e1', entity_type: 'data_product', entity_id: 'p1', action: 'UPDATE' },
    ])) as any;
    renderWithProviders(<RecentActivity />);
    expect(await screen.findByText(/UPDATE/)).toBeTruthy();
  });

  it('shows no empty state until the change log answers', async () => {
    let release: (v: any) => void = () => {};
    globalThis.fetch = vi.fn(() => new Promise((r) => { release = r; })) as any;
    renderWithProviders(<RecentActivity />);
    expect(screen.queryByText('No recent activity.')).toBeNull();
    release(answer(200, []));
    expect(await screen.findByText('No recent activity.')).toBeTruthy();
  });
});
