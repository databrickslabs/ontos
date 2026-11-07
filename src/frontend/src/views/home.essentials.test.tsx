/** The home page by edition: Full is unchanged, Essentials is organized by journey. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { FeatureAccessLevel } from '@/types/settings';
import { ACCESS_LEVEL_ORDER } from '@/lib/permissions';

const state = vi.hoisted(() => {
  // The UI customization store fetches on import; keep it offline until a test sets routes.
  const s = {
    perms: {} as Record<string, string>,
    routes: {} as Record<string, unknown>,
    calls: [] as string[],
    roles: [] as unknown[],
  };
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    s.calls.push(url);
    const key = Object.keys(s.routes)
      .sort((a, b) => b.length - a.length)
      .find((k) => url.startsWith(k));
    if (!key) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => s.routes[key] };
  }) as any;
  return s;
});

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    isLoading: false,
    permissions: state.perms,
    hasPermission: (id: string, level: FeatureAccessLevel) =>
      (ACCESS_LEVEL_ORDER as Record<string, number>)[state.perms[id] || 'None'] >=
      (ACCESS_LEVEL_ORDER as Record<string, number>)[level],
    availableRoles: state.roles,
    requestableRoles: [],
    appliedRoleId: null,
  }),
}));
// Sections with their own data and tests; stubbed to keep this test on the layout.
vi.mock('@/components/home/required-actions-section', () => ({
  default: () => <div data-testid="required-actions" />,
}));
vi.mock('@/components/home/recent-activity', () => ({
  default: () => <div data-testid="recent-activity" />,
}));
vi.mock('@/components/home/discovery-section', () => ({
  default: () => <div data-testid="discovery-section" />,
}));

import Home from './home';
import { features } from '@/config/features';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { useUserStore } from '@/stores/user-store';
import {
  assetGaps,
  latestReviewedAssets,
  myOpenReviews,
  reviewStatusCounts,
} from '@/components/home/essentials/use-essentials-data';
import { ReviewRequestStatus, ReviewedAssetStatus } from '@/types/data-asset-review';

const RW = FeatureAccessLevel.READ_WRITE;
const RO = FeatureAccessLevel.READ_ONLY;
const ALL_PERMS = {
  'data-catalog': RW, assets: RW, 'semantic-models': RW, 'data-asset-reviews': RW,
  'access-grants': RW, 'data-products': RW, 'data-contracts': RW, compliance: RW,
};

const review = (
  id: string, status: string, requester: string, reviewer: string,
  assets: { fqn: string; status: string; at: string }[],
) => ({
  id, title: `Review ${id}`, status, requester_email: requester, reviewer_email: reviewer,
  created_at: '2026-01-01', updated_at: '2026-01-01',
  assets: assets.map((a) => ({
    id: a.fqn, asset_fqn: a.fqn, asset_type: 'table', status: a.status, updated_at: a.at,
  })),
});

const REVIEWS = [
  review('r1', 'in_review', 'me@x.com', 'boss@x.com', [
    { fqn: 'main.sales.orders', status: 'approved', at: '2026-03-02' },
    { fqn: 'main.sales.refunds', status: 'pending', at: '2026-03-01' },
  ]),
  review('r2', 'approved', 'other@x.com', 'boss@x.com', [
    { fqn: 'main.hr.people', status: 'rejected', at: '2026-02-01' },
  ]),
];

function setRoutes() {
  state.routes = {
    '/api/assets?limit=1': { items: [], total: 42, skip: 0, limit: 1 },
    '/api/assets/a1': { id: 'a1', name: 'orders', location: 'main.sales.orders',
      description: 'Orders' },
    '/api/assets/a2': { id: 'a2', name: 'customers', location: 'main.sales.customers',
      description: '' },
    '/api/user/ownerships': [
      { object_type: 'asset', object_id: 'a1' },
      { object_type: 'asset', object_id: 'a2' },
      { object_type: 'data_product', object_id: 'p1' },
    ],
    '/api/data-asset-reviews': REVIEWS,
    '/api/access-grants/my-requests': { requests: [
      { id: 'g1', entity_name: 'Sales tables', entity_id: 'e1', entity_type: 'asset',
        status: 'pending', created_at: '2026-03-01' },
      { id: 'g2', entity_name: 'Old', entity_id: 'e2', entity_type: 'asset',
        status: 'approved', created_at: '2026-01-01' },
    ], total: 2 },
    '/api/semantic-models/stats': { stats: { taxonomies: [], total_concepts: 7,
      total_properties: 0 } },
  };
}

const essentialsPaths = new Set(
  features.filter((f) => f.editions.includes('essentials')).map((f) => f.path),
);

describe('Home by edition', () => {
  beforeEach(() => {
    state.perms = { ...ALL_PERMS };
    state.calls = [];
    state.roles = [];
    setRoutes();
    useFeatureVisibilityStore.setState({
      showAllFeatures: false, allowedMaturities: ['ga', 'beta'],
    });
    useUserStore.setState({
      userInfo: { email: 'me@x.com', username: 'me', user: 'me', ip: null, groups: [] } as any,
    });
  });

  it('Full keeps today\'s home (overview, my actions, discovery, activity)', () => {
    useUICustomizationStore.setState({ edition: 'full' });
    renderWithProviders(<Home />);
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('My Actions')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-section')).toBeInTheDocument();
    expect(screen.getByTestId('recent-activity')).toBeInTheDocument();
    expect(screen.queryByTestId('essentials-home')).not.toBeInTheDocument();
  });

  it('Essentials renders the five journey sections and pending approvals', async () => {
    useUICustomizationStore.setState({ edition: 'essentials' });
    renderWithProviders(<Home />);
    for (const id of ['find', 'understand', 'trust', 'publish', 'maintain']) {
      expect(screen.getByTestId(`essentials-section-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId('required-actions')).toBeInTheDocument();
    expect(screen.queryByText('Overview')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-section')).not.toBeInTheDocument();

    const trust = screen.getByTestId('essentials-section-trust');
    await waitFor(() => expect(within(trust).getByText('main.sales.orders')).toBeInTheDocument());
    expect(within(trust).getByText('main.sales.orders').closest('a')).toHaveAttribute(
      'href', '/data-catalog/main.sales.orders',
    );
    expect(within(screen.getByTestId('essentials-trust-counts')).getByText('Approved: 1'))
      .toBeInTheDocument();
    await waitFor(() =>
      expect(within(screen.getByTestId('essentials-section-understand')).getByText('42'))
        .toBeInTheDocument(),
    );
  });

  it('Essentials links only to features the Essentials edition shows', async () => {
    useUICustomizationStore.setState({ edition: 'essentials' });
    renderWithProviders(<Home />);
    await waitFor(() => expect(screen.getByTestId('essentials-publish-gaps')).toBeInTheDocument());
    const hrefs = Array.from(
      screen.getByTestId('essentials-home').querySelectorAll('a'),
    ).map((a) => a.getAttribute('href') || '');
    expect(hrefs.length).toBeGreaterThan(5);
    for (const href of hrefs) {
      const root = '/' + href.split('/')[1];
      expect(essentialsPaths.has(root)).toBe(true);
    }
    expect(hrefs.some((h) => h.startsWith('/data-products') || h.startsWith('/data-contracts')))
      .toBe(false);
  });

  it('Essentials hides the sections the user cannot read', async () => {
    state.perms = { assets: RO };
    useUICustomizationStore.setState({ edition: 'essentials' });
    renderWithProviders(<Home />);
    expect(screen.getByTestId('essentials-section-find')).toBeInTheDocument();
    expect(screen.getByTestId('essentials-section-understand')).toBeInTheDocument();
    expect(screen.queryByTestId('essentials-section-trust')).not.toBeInTheDocument();
    expect(screen.queryByTestId('essentials-section-publish')).not.toBeInTheDocument();
    expect(screen.queryByTestId('essentials-maintain-requests')).not.toBeInTheDocument();
    expect(screen.queryByTestId('essentials-maintain-reviews')).not.toBeInTheDocument();
    expect(screen.getByText('Nothing to follow up.')).toBeInTheDocument();
    expect(screen.queryByText('Browse the Data Catalog')).not.toBeInTheDocument();
    await waitFor(() => expect(state.calls).toContain('/api/assets?limit=1'));
    expect(state.calls.some((u) => u.startsWith('/api/data-asset-reviews'))).toBe(false);
    expect(state.calls).not.toContain('/api/user/ownerships');
    expect(state.calls).not.toContain('/api/access-grants/my-requests');
  });

  it('Publish lists owned assets with gaps and offers a review request', async () => {
    useUICustomizationStore.setState({ edition: 'essentials' });
    renderWithProviders(<Home />);
    const list = await screen.findByTestId('essentials-publish-gaps');
    expect(within(list).getByText('customers')).toHaveAttribute('href', '/assets/a2');
    expect(within(list).queryByText('orders')).not.toBeInTheDocument();
    expect(within(list).getByText('No description')).toBeInTheDocument();
    expect(within(list).getByText('Not reviewed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Request a review/ })).toBeInTheDocument();
  });

  it('Maintain shows my pending requests and my open reviews', async () => {
    useUICustomizationStore.setState({ edition: 'essentials' });
    renderWithProviders(<Home />);
    const requests = screen.getByTestId('essentials-maintain-requests');
    await waitFor(() => expect(within(requests).getByText('Sales tables')).toBeInTheDocument());
    expect(within(requests).queryByText('Old')).not.toBeInTheDocument();
    expect(within(requests).getByText('My pending requests (1)')).toBeInTheDocument();
    const reviews = screen.getByTestId('essentials-maintain-reviews');
    await waitFor(() => expect(within(reviews).getByText('Review r1')).toBeInTheDocument());
    expect(within(reviews).getByText('Review r1')).toHaveAttribute(
      'href', '/data-asset-reviews/r1',
    );
    expect(within(reviews).queryByText('Review r2')).not.toBeInTheDocument();
  });

  it('"Show all features" gives an admin the Full home, not a non-admin', () => {
    useUICustomizationStore.setState({ edition: 'essentials' });
    useFeatureVisibilityStore.setState({ showAllFeatures: true });
    const first = renderWithProviders(<Home />);
    expect(screen.getByTestId('essentials-home')).toBeInTheDocument();
    first.unmount();

    state.roles = [{ id: 'admin', name: 'Admin', is_admin: true, assigned_groups: ['admins'] }];
    useUserStore.setState({
      userInfo: { email: 'me@x.com', username: 'me', user: 'me', ip: null,
        groups: ['admins'] } as any,
    });
    renderWithProviders(<Home />);
    expect(screen.queryByTestId('essentials-home')).not.toBeInTheDocument();
    expect(screen.getByText('Overview')).toBeInTheDocument();
  });
});

describe('Essentials home data helpers', () => {
  const reviews = REVIEWS as any;

  it('counts reviewed assets per status', () => {
    expect(reviewStatusCounts(reviews)).toEqual({
      [ReviewedAssetStatus.APPROVED]: 1,
      [ReviewedAssetStatus.PENDING]: 1,
      [ReviewedAssetStatus.NEEDS_CLARIFICATION]: 0,
      [ReviewedAssetStatus.REJECTED]: 1,
    });
  });

  it('lists the latest reviewed assets first', () => {
    expect(latestReviewedAssets(reviews, 2).map((a) => a.fqn)).toEqual(
      ['main.sales.orders', 'main.sales.refunds'],
    );
  });

  it('keeps open reviews where I am requester or reviewer', () => {
    expect(myOpenReviews(reviews, 'ME@x.com').map((r) => r.id)).toEqual(['r1']);
    expect(myOpenReviews(reviews, 'boss@x.com').map((r) => r.id)).toEqual(['r1']);
    expect(myOpenReviews(reviews, null)).toEqual([]);
    expect(ReviewRequestStatus.APPROVED).toBe('approved');
  });

  it('leaves the review state unknown when reviews are not readable', () => {
    const assets = [
      { id: 'a1', name: 'orders', location: 'main.sales.orders', description: 'x' },
      { id: 'a2', name: 'customers', location: null, description: ' ' },
    ];
    expect(assetGaps(assets, null)).toEqual([
      { asset: assets[1], missingDescription: true, missingReview: null },
    ]);
    expect(assetGaps(assets, reviews).map((g) => g.asset.id)).toEqual(['a2']);
  });
});
