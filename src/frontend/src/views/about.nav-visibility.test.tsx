/** The About page lists only the features the user's menus show (#1325). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';

const state = vi.hoisted(() => {
  // About and the UI customization store fetch on load; keep them offline.
  globalThis.fetch = (async () => ({ ok: false, json: async () => ({}) })) as any;
  return { hiddenNavFeatures: [] as string[], appliedRoleId: null as string | null };
});

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    isLoading: false,
    availableRoles: [{ id: 'r-admin', name: 'Admin', assigned_groups: ['admins'], is_admin: true }],
    hiddenNavFeatures: state.hiddenNavFeatures,
    appliedRoleId: state.appliedRoleId,
  }),
}));

import About from './about';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import { useUserStore } from '@/stores/user-store';

const setGroups = (groups: string[]) =>
  useUserStore.setState({
    userInfo: { email: 'u@example.com', username: 'u', user: 'u', ip: null, groups },
  });

describe('About with hidden features', () => {
  beforeEach(() => {
    useFeatureVisibilityStore.setState({ allowedMaturities: ['ga'] });
    useUICustomizationStore.setState({ aboutContent: null } as any);
    state.hiddenNavFeatures = [];
    state.appliedRoleId = null;
    setGroups(['consumers']);
  });

  it('lists the core features when nothing is hidden', () => {
    renderWithProviders(<About />);
    expect(screen.getByText('Contracts')).toBeInTheDocument();
    expect(screen.getByText('Products')).toBeInTheDocument();
  });

  it('leaves out the hidden features', () => {
    state.hiddenNavFeatures = ['data-contracts', 'data-products'];
    renderWithProviders(<About />);
    expect(screen.queryByText('Contracts')).not.toBeInTheDocument();
    expect(screen.queryByText('Products')).not.toBeInTheDocument();
    expect(screen.getByText('Assets')).toBeInTheDocument();
  });

  it('lists everything for an Ontos admin acting as themselves', () => {
    setGroups(['admins']);
    state.hiddenNavFeatures = ['data-contracts'];
    renderWithProviders(<About />);
    expect(screen.getByText('Contracts')).toBeInTheDocument();
  });
});
