/**
 * The sidebar leaves out the features the user's roles hide from navigation (#1325),
 * at Read-only and at Read/Write alike; an Ontos admin acting as themselves sees all.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { features } from '@/config/features';
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

const adminRole = { id: 'r-admin', name: 'Admin', assigned_groups: ['admins'], is_admin: true };
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    permissions: state.permissions,
    isLoading: false,
    hasPermission: (id: string, level: string) => {
      const order = ['None', 'Read-only', 'Filtered', 'Read/Write', 'Full', 'Admin'];
      return order.indexOf(state.permissions[id] ?? 'None') >= order.indexOf(level);
    },
    availableRoles: [adminRole],
    hiddenNavFeatures: state.hiddenNavFeatures,
    appliedRoleId: state.appliedRoleId,
  }),
}));

import { Navigation } from './navigation';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { useUserStore } from '@/stores/user-store';

const setGroups = (groups: string[]) =>
  useUserStore.setState({
    userInfo: { email: 'u@example.com', username: 'u', user: 'u', ip: null, groups },
  });

const navPaths = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('a'))
    .map((a) => a.getAttribute('href'))
    .filter((href): href is string => !!href && href !== '/');

const RO = FeatureAccessLevel.READ_ONLY;
const RW = FeatureAccessLevel.READ_WRITE;

describe('Navigation with hidden features', () => {
  beforeEach(() => {
    useFeatureVisibilityStore.setState({
      showBeta: true, showAlpha: true, allowedMaturities: ['ga', 'beta', 'alpha'],
    });
    state.permissions = {
      'data-catalog': RO, 'data-contracts': RO, 'data-products': RW, assets: RW,
    };
    state.hiddenNavFeatures = [];
    state.appliedRoleId = null;
    setGroups(['consumers']);
  });

  it('shows every accessible feature when nothing is hidden', () => {
    const { container } = renderWithProviders(<Navigation isCollapsed={false} />);
    expect(navPaths(container).sort()).toEqual(
      ['/assets', '/data-catalog', '/data-contracts', '/data-products', '/marketplace'],
    );
  });

  it('leaves out a hidden feature at Read-only and one at Read/Write', () => {
    state.hiddenNavFeatures = ['data-contracts', 'data-products'];
    const { container } = renderWithProviders(<Navigation isCollapsed={false} />);
    // data-products also gates Marketplace, so both entries go.
    expect(navPaths(container).sort()).toEqual(['/assets', '/data-catalog']);
  });

  it('shows everything to an Ontos admin acting as themselves', () => {
    setGroups(['admins']);
    state.permissions = Object.fromEntries(
      features.map((f) => [f.permissionId || f.id, FeatureAccessLevel.ADMIN]),
    );
    state.hiddenNavFeatures = ['data-contracts', 'assets'];
    const { container } = renderWithProviders(<Navigation isCollapsed={false} />);
    expect(navPaths(container)).toEqual(expect.arrayContaining(['/data-contracts', '/assets']));
  });

  it("shows the switched role's menu to an admin using the role switcher", () => {
    setGroups(['admins']);
    state.appliedRoleId = 'r-consumer';
    state.hiddenNavFeatures = ['data-contracts'];
    const { container } = renderWithProviders(<Navigation isCollapsed={false} />);
    expect(navPaths(container)).not.toContain('/data-contracts');
    expect(navPaths(container)).toContain('/data-catalog');
  });
});
