/** Home quick actions leave out the features the user's roles hide from navigation (#1325). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { FeatureAccessLevel } from '@/types/settings';

const state = vi.hoisted(() => {
  // The UI customization store fetches on import; keep it offline.
  globalThis.fetch = (async () => ({ ok: false, json: async () => ({}) })) as any;
  return {
    permissions: {} as Record<string, string>,
    hiddenNavFeatures: [] as string[],
    appliedRoleId: null as string | null,
  };
});

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    isLoading: false,
    hasPermission: (id: string, level: string) => {
      const order = ['None', 'Read-only', 'Filtered', 'Read/Write', 'Full', 'Admin'];
      return order.indexOf(state.permissions[id] ?? 'None') >= order.indexOf(level);
    },
    availableRoles: [{ id: 'r-admin', name: 'Admin', assigned_groups: ['admins'], is_admin: true }],
    hiddenNavFeatures: state.hiddenNavFeatures,
    appliedRoleId: state.appliedRoleId,
  }),
}));

import QuickActions from './quick-actions';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { useUserStore } from '@/stores/user-store';

const actionPaths = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href')).sort();

const setGroups = (groups: string[]) =>
  useUserStore.setState({
    userInfo: { email: 'u@example.com', username: 'u', user: 'u', ip: null, groups },
  });

describe('QuickActions with hidden features', () => {
  beforeEach(() => {
    useFeatureVisibilityStore.setState({ allowedMaturities: ['ga', 'beta', 'alpha'] });
    state.permissions = {
      'data-catalog': FeatureAccessLevel.READ_ONLY,
      'data-products': FeatureAccessLevel.READ_WRITE,
      assets: FeatureAccessLevel.READ_WRITE,
    };
    state.hiddenNavFeatures = [];
    state.appliedRoleId = null;
    setGroups(['consumers']);
  });

  // data-products resolves to its first menu entry, Marketplace, for both of its actions.
  it('offers every accessible feature when nothing is hidden', () => {
    const { container } = renderWithProviders(<QuickActions />);
    expect(actionPaths(container)).toEqual(
      ['/assets', '/data-catalog', '/marketplace', '/marketplace'],
    );
  });

  it('drops a hidden feature at Read-only and one at Read/Write', () => {
    state.hiddenNavFeatures = ['data-catalog', 'data-products'];
    const { container } = renderWithProviders(<QuickActions />);
    expect(actionPaths(container)).toEqual(['/assets']);
  });

  it('keeps every action for an Ontos admin acting as themselves', () => {
    setGroups(['admins']);
    state.hiddenNavFeatures = ['data-catalog', 'data-products'];
    const { container } = renderWithProviders(<QuickActions />);
    expect(actionPaths(container)).toEqual(
      ['/assets', '/data-catalog', '/marketplace', '/marketplace'],
    );
  });
});
