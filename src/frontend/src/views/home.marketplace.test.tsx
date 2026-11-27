/** The marketplace home section replaces the home page for users who can read products (#1325). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { FeatureAccessLevel, HomeSection } from '@/types/settings';
import { ACCESS_LEVEL_ORDER } from '@/lib/permissions';

const state = vi.hoisted(() => {
  // The UI customization store fetches on import; keep it offline.
  globalThis.fetch = (async () => ({ ok: false, status: 404, json: async () => ({}) })) as any;
  return {
    perms: {} as Record<string, string>,
    roles: [] as unknown[],
    applied: null as string | null,
  };
});

vi.mock('@/stores/permissions-store', () => {
  const hasPermission = (id: string, level: FeatureAccessLevel) =>
    (ACCESS_LEVEL_ORDER as Record<string, number>)[state.perms[id] || 'None'] >=
    (ACCESS_LEVEL_ORDER as Record<string, number>)[level];
  return {
    usePermissions: () => ({
      isLoading: false,
      permissions: state.perms,
      hasPermission,
      availableRoles: state.roles,
      requestableRoles: [],
      appliedRoleId: state.applied,
      hiddenNavFeatures: [],
    }),
  };
});
vi.mock('@/components/home/marketplace-view', () => ({
  default: () => <div data-testid="marketplace-view" />,
}));
vi.mock('@/components/home/essentials/essentials-home', () => ({
  default: () => <div data-testid="essentials-home" />,
  readsApprovalQueue: () => true,
}));
vi.mock('@/components/home/required-actions-section', () => ({
  default: () => <div data-testid="required-actions" />,
}));
vi.mock('@/components/home/recent-activity', () => ({
  default: () => <div data-testid="recent-activity" />,
}));
vi.mock('@/components/home/discovery-section', () => ({
  default: () => <div data-testid="discovery-section" />,
}));
vi.mock('@/components/home/data-curation-section', () => ({
  default: () => <div data-testid="data-curation-section" />,
}));
vi.mock('@/components/home/quick-actions', () => ({ default: () => <div /> }));
vi.mock('@/components/home/connected-overview-tile', () => ({ default: () => <div /> }));

import Home from './home';
import { useUserStore } from '@/stores/user-store';

const RO = FeatureAccessLevel.READ_ONLY;

const applyRole = (sections: HomeSection[], extra: HomeSection[][] = []) => {
  state.roles = [sections, ...extra].map((home_sections, i) => ({
    id: `r${i}`, name: `Role ${i}`, assigned_groups: ['g'], home_sections,
  }));
  state.applied = null;
  useUserStore.setState({
    userInfo: { email: 'me@x.com', username: 'me', user: 'me', ip: null, groups: ['g'] } as any,
  });
};

describe('Home with the marketplace home section', () => {
  beforeEach(() => {
    state.perms = { 'data-products': RO, 'data-catalog': RO };
    state.roles = [];
    state.applied = null;
  });

  it('renders the marketplace and nothing else', () => {
    applyRole([HomeSection.MARKETPLACE]);
    renderWithProviders(<Home />);

    expect(screen.getByTestId('marketplace-view')).toBeInTheDocument();
    expect(screen.queryByText('Overview')).not.toBeInTheDocument();
    expect(screen.queryByText('My Actions')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-section')).not.toBeInTheDocument();
    expect(screen.queryByTestId('recent-activity')).not.toBeInTheDocument();
    expect(screen.queryByTestId('essentials-home')).not.toBeInTheDocument();
  });

  it('falls back to the full home without read access to products', () => {
    state.perms = { 'data-catalog': RO };
    applyRole([HomeSection.MARKETPLACE]);
    renderWithProviders(<Home />);

    expect(screen.queryByTestId('marketplace-view')).not.toBeInTheDocument();
    expect(screen.getByText('Overview')).toBeInTheDocument();
    // MARKETPLACE has no section of its own: the default section shows.
    expect(screen.getByTestId('discovery-section')).toBeInTheDocument();
  });

  it('lets the journey win on a union of roles', () => {
    applyRole([HomeSection.MARKETPLACE], [[HomeSection.JOURNEY]]);
    renderWithProviders(<Home />);

    expect(screen.getByTestId('essentials-home')).toBeInTheDocument();
    expect(screen.queryByTestId('marketplace-view')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-section')).not.toBeInTheDocument();
  });

  it('keeps the other sections of a union out of the marketplace home', () => {
    applyRole([HomeSection.MARKETPLACE], [[HomeSection.DISCOVERY]]);
    renderWithProviders(<Home />);

    expect(screen.getByTestId('marketplace-view')).toBeInTheDocument();
    expect(screen.queryByTestId('discovery-section')).not.toBeInTheDocument();
  });

  it('lets the curation and required-actions sections of another role win', () => {
    applyRole(
      [HomeSection.MARKETPLACE],
      [[HomeSection.REQUIRED_ACTIONS, HomeSection.DATA_CURATION, HomeSection.DISCOVERY]],
    );
    renderWithProviders(<Home />);

    expect(screen.queryByTestId('marketplace-view')).not.toBeInTheDocument();
    expect(screen.getByTestId('data-curation-section')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-section')).toBeInTheDocument();
    expect(screen.getByTestId('required-actions')).toBeInTheDocument();
  });

  it('shows the full home as before when no role has the marketplace section', () => {
    applyRole([HomeSection.DISCOVERY]);
    renderWithProviders(<Home />);

    expect(screen.queryByTestId('marketplace-view')).not.toBeInTheDocument();
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-section')).toBeInTheDocument();
  });
});
