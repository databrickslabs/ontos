import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { FeatureAccessLevel } from '@/types/settings';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (_k: string, fallback?: string) => fallback ?? _k }),
}));

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual: any = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => navigateMock };
});

const setRoleOverrideMock = vi.fn();
const initializeStoreMock = vi.fn();

interface MockPermissionsState {
  permissions: Record<string, FeatureAccessLevel>;
  actualPermissions: Record<string, FeatureAccessLevel>;
  isLoading: boolean;
  availableRoles: any[];
  appliedRoleId: string | null;
  setRoleOverride: typeof setRoleOverrideMock;
  initializeStore: typeof initializeStoreMock;
  hasPermission: (featureId: string, requiredLevel: FeatureAccessLevel) => boolean;
}

let permissionsState: MockPermissionsState;

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => permissionsState,
}));

vi.mock('@/stores/feature-visibility-store', () => ({
  useFeatureVisibilityStore: () => ({
    showBeta: false,
    showAlpha: false,
    actions: { toggleBeta: vi.fn(), toggleAlpha: vi.fn() },
  }),
}));

// Dialog is irrelevant for these tests; stub it out so we don't need its deps.
vi.mock('@/components/ui/user-profile-dialog', () => ({
  default: () => null,
}));

import UserInfo from './user-info';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Admin-style impersonation is now gated on `is_admin` role membership (see #404),
// not on `settings:ADMIN`. The fixture mirrors that: the canonical Admin role carries
// is_admin=true, while a separate "Settings Admin" role grants settings:ADMIN without
// admin powers — used by the regression case below.
const adminRole = {
  id: 'role-admin',
  name: 'Admin',
  assigned_groups: ['admins'],
  feature_permissions: { settings: FeatureAccessLevel.ADMIN },
  is_admin: true,
};
const settingsAdminRole = {
  id: 'role-settings-admin',
  name: 'Settings Admin',
  assigned_groups: ['settings-admins'],
  feature_permissions: { settings: FeatureAccessLevel.ADMIN },
  is_admin: false,
};
const producerRole = {
  id: 'role-producer',
  name: 'Data Producer',
  assigned_groups: ['data-producers'],
  feature_permissions: { 'data-products': FeatureAccessLevel.READ_WRITE },
  is_admin: false,
};
const stewardRole = {
  id: 'role-steward',
  name: 'Data Steward',
  assigned_groups: ['data-stewards'],
  feature_permissions: { 'data-products': FeatureAccessLevel.READ_WRITE },
  is_admin: false,
};
const consumerRole = {
  id: 'role-consumer',
  name: 'Data Consumer',
  assigned_groups: ['data-consumers'],
  feature_permissions: { 'data-products': FeatureAccessLevel.READ_ONLY },
  is_admin: false,
};

const mockUserDetailsFetch = (groups: string[], username: string = 'test.user') => {
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.includes('/api/user/details') || url.includes('/api/user/info')) {
      return {
        ok: true,
        json: async () => ({
          email: `${username}@example.com`,
          username,
          user: username,
          ip: '127.0.0.1',
          groups,
        }),
      } as Response;
    }
    if (url.includes('/api/user/actual-role')) {
      return {
        ok: true,
        json: async () => ({ role: null }),
      } as Response;
    }
    return { ok: false, json: async () => ({}) } as Response;
  }) as any;
};

const openMenu = async () => {
  const user = userEvent.setup();
  const trigger = await screen.findByRole('button');
  await user.click(trigger);
  return user;
};

describe('UserInfo role switcher gating', () => {
  beforeEach(() => {
    setRoleOverrideMock.mockReset();
    initializeStoreMock.mockReset();
    navigateMock.mockReset();
    permissionsState = {
      permissions: {},
      actualPermissions: {},
      isLoading: false,
      availableRoles: [adminRole, settingsAdminRole, producerRole, stewardRole, consumerRole],
      appliedRoleId: null,
      setRoleOverride: setRoleOverrideMock,
      initializeStore: initializeStoreMock,
      hasPermission: () => true,
    };
  });

  it('shows all non-canonical roles in the switcher for users in the is_admin role', async () => {
    // Membership in a role with is_admin=true is what unlocks the full switcher,
    // not the settings:ADMIN feature permission (see #404).
    mockUserDetailsFetch(['admins'], 'admin.user');

    renderWithProviders(<UserInfo />);
    await openMenu();

    // Switcher label present
    expect(await screen.findByText('userMenu.applyRoleOverride')).toBeInTheDocument();
    // Admin sees all roles in the radio list (Settings Admin included)
    expect(screen.getByText('Admin')).toBeInTheDocument();
    expect(screen.getByText('Settings Admin')).toBeInTheDocument();
    expect(screen.getByText('Data Producer')).toBeInTheDocument();
    expect(screen.getByText('Data Steward')).toBeInTheDocument();
    expect(screen.getByText('Data Consumer')).toBeInTheDocument();
  });

  it('does NOT grant admin impersonation to users with settings:ADMIN but no is_admin role (regression for #404)', async () => {
    // The user belongs only to the "Settings Admin" role (settings:ADMIN, is_admin=false).
    // Before the fix this implicitly elevated them and showed the full role catalog;
    // after the fix they fall into the non-admin path and only see their membership-matched role.
    mockUserDetailsFetch(['settings-admins'], 'settings.admin');
    permissionsState.actualPermissions = { settings: FeatureAccessLevel.ADMIN };

    renderWithProviders(<UserInfo />);
    await openMenu();

    await waitFor(() => {
      expect(screen.getByText('userMenu.profile')).toBeInTheDocument();
    });

    // With only one membership-matched role, the switcher is not shown at all
    // (matches existing "single membership" gating).
    expect(screen.queryByText('userMenu.applyRoleOverride')).not.toBeInTheDocument();
    // And critically, no other roles leak into the UI.
    expect(screen.queryByText('Admin')).not.toBeInTheDocument();
    expect(screen.queryByText('Data Producer')).not.toBeInTheDocument();
    expect(screen.queryByText('Data Consumer')).not.toBeInTheDocument();
  });

  it('shows only membership-matched roles for non-admin user in 2+ roles', async () => {
    mockUserDetailsFetch(['data-producers', 'data-stewards']);
    permissionsState.actualPermissions = { 'data-products': FeatureAccessLevel.READ_WRITE };

    renderWithProviders(<UserInfo />);
    await openMenu();

    // Switcher visible
    expect(await screen.findByText('userMenu.applyRoleOverride')).toBeInTheDocument();
    // Membership roles present
    expect(screen.getByText('Data Producer')).toBeInTheDocument();
    expect(screen.getByText('Data Steward')).toBeInTheDocument();
    // Non-membership roles MUST be hidden
    expect(screen.queryByText('Admin')).not.toBeInTheDocument();
    expect(screen.queryByText('Data Consumer')).not.toBeInTheDocument();
  });

  it('does not render the switcher for non-admin user in a single role', async () => {
    mockUserDetailsFetch(['data-producers']);
    permissionsState.actualPermissions = { 'data-products': FeatureAccessLevel.READ_WRITE };

    renderWithProviders(<UserInfo />);
    await openMenu();

    await waitFor(() => {
      // Other menu items render — we just don't see the switcher label.
      expect(screen.getByText('userMenu.profile')).toBeInTheDocument();
    });
    expect(screen.queryByText('userMenu.applyRoleOverride')).not.toBeInTheDocument();
  });

  it('does not render the switcher for non-admin user in zero matched roles', async () => {
    mockUserDetailsFetch(['random-unmatched-group']);
    permissionsState.actualPermissions = {};

    renderWithProviders(<UserInfo />);
    await openMenu();

    await waitFor(() => {
      expect(screen.getByText('userMenu.profile')).toBeInTheDocument();
    });
    expect(screen.queryByText('userMenu.applyRoleOverride')).not.toBeInTheDocument();
  });

  it('matches groups case-insensitively', async () => {
    mockUserDetailsFetch(['Data-Producers', 'DATA-STEWARDS']);
    permissionsState.actualPermissions = { 'data-products': FeatureAccessLevel.READ_WRITE };

    renderWithProviders(<UserInfo />);
    await openMenu();

    expect(await screen.findByText('userMenu.applyRoleOverride')).toBeInTheDocument();
    expect(screen.getByText('Data Producer')).toBeInTheDocument();
    expect(screen.getByText('Data Steward')).toBeInTheDocument();
  });
});
