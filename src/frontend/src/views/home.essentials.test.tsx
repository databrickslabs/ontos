/** The home page by role home section: Full is unchanged, JOURNEY replaces it (#1347). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { FeatureAccessLevel, HomeSection } from '@/types/settings';
import { ACCESS_LEVEL_ORDER } from '@/lib/permissions';
import i18n from '@/i18n/config';

const state = vi.hoisted(() => {
  // The UI customization store fetches on import; keep it offline until a test sets routes.
  const s = {
    perms: {} as Record<string, string>,
    routes: {} as Record<string, unknown>,
    calls: [] as string[],
    roles: [] as unknown[],
    applied: null as string | null,
    hidden: [] as string[],
  };
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    s.calls.push(url);
    const key = Object.keys(s.routes)
      .sort((a, b) => b.length - a.length)
      .find((k) => url.startsWith(k));
    if (!key) return { ok: false, status: 404, json: async () => ({}) };
    const body = s.routes[key];
    const data = typeof body === 'function' ? (body as (u: string) => unknown)(url) : body;
    return { ok: true, status: 200, json: async () => data };
  }) as any;
  return s;
});

vi.mock('@/stores/permissions-store', () => {
  // Stable like the real store's: tiles re-fetch whenever `hasPermission` changes.
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
      hiddenNavFeatures: state.hidden,
    }),
  };
});
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
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { useUserStore } from '@/stores/user-store';
import { useEssentialsHomePreferencesStore } from '@/stores/essentials-home-preferences-store';
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

let owned: { id: string; name: string; location: string; description: string }[] = [];

/** `GET /api/assets?owned_by_me=true&skip=&limit=` over the `owned` fixture. */
function ownedPage(url: string) {
  const q = new URL(url, 'http://x').searchParams;
  const skip = Number(q.get('skip')), limit = Number(q.get('limit'));
  return { items: owned.slice(skip, skip + limit), total: owned.length, skip, limit };
}

function setRoutes() {
  owned = [
    { id: 'a1', name: 'orders', location: 'main.sales.orders', description: 'Orders' },
    { id: 'a2', name: 'customers', location: 'main.sales.customers', description: '' },
  ];
  state.routes = {
    '/api/assets?limit=1': { items: [], total: 42, skip: 0, limit: 1 },
    '/api/assets?owned_by_me=true': ownedPage,
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

const menuPaths = new Set(features.map((f) => f.path));

/** Applies a role whose home sections include the journey home. */
function applyJourneyRole(sections: HomeSection[] = [HomeSection.JOURNEY]) {
  state.roles = [{ id: 'journey', name: 'Journey', home_sections: sections, assigned_groups: [] }];
  state.applied = 'journey';
}

describe('Home by role home section', () => {
  beforeEach(() => {
    state.perms = { ...ALL_PERMS };
    state.calls = [];
    state.roles = [];
    state.applied = null;
    state.hidden = [];
    setRoutes();
    useEssentialsHomePreferencesStore.setState({ publishPageSize: 10 });
    useFeatureVisibilityStore.setState({
      showBeta: true, showAlpha: false, allowedMaturities: ['ga', 'beta'],
    });
    useUserStore.setState({
      userInfo: { email: 'me@x.com', username: 'me', user: 'me', ip: null, groups: [] } as any,
    });
  });

  it('Full keeps today\'s home (overview, my actions, discovery, activity)', () => {
    renderWithProviders(<Home />);
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('My Actions')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-section')).toBeInTheDocument();
    expect(screen.getByTestId('recent-activity')).toBeInTheDocument();
    expect(screen.queryByTestId('essentials-home')).not.toBeInTheDocument();
  });

  it('the journey renders the five sections and pending approvals', async () => {
    applyJourneyRole();
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

  it('the journey links only to features the menus show', async () => {
    applyJourneyRole();
    renderWithProviders(<Home />);
    await waitFor(() => expect(screen.getByTestId('essentials-publish-gaps')).toBeInTheDocument());
    const hrefs = Array.from(
      screen.getByTestId('essentials-home').querySelectorAll('a'),
    ).map((a) => a.getAttribute('href') || '');
    expect(hrefs.length).toBeGreaterThan(5);
    for (const href of hrefs) {
      const root = '/' + href.split('/')[1];
      expect(menuPaths.has(root)).toBe(true);
    }
    expect(hrefs.some((h) => h.startsWith('/data-products') || h.startsWith('/data-contracts')))
      .toBe(false);
  });

  it('the journey hides the sections the user cannot read', async () => {
    state.perms = { assets: RO };
    applyJourneyRole();
    renderWithProviders(<Home />);
    expect(screen.getByTestId('essentials-section-find')).toBeInTheDocument();
    expect(screen.getByTestId('essentials-section-understand')).toBeInTheDocument();
    expect(screen.queryByTestId('essentials-section-trust')).not.toBeInTheDocument();
    expect(screen.queryByTestId('essentials-section-publish')).not.toBeInTheDocument();
    expect(screen.queryByTestId('essentials-section-maturity')).not.toBeInTheDocument();
    expect(screen.queryByTestId('essentials-maintain-requests')).not.toBeInTheDocument();
    expect(screen.queryByTestId('essentials-maintain-reviews')).not.toBeInTheDocument();
    expect(screen.getByText('Nothing to follow up.')).toBeInTheDocument();
    expect(screen.queryByText('Browse the Data Catalog')).not.toBeInTheDocument();
    await waitFor(() => expect(state.calls).toContain('/api/assets?limit=1'));
    expect(state.calls.some((u) => u.startsWith('/api/data-asset-reviews'))).toBe(false);
    expect(state.calls.some((u) => u.includes('owned_by_me'))).toBe(false);
    expect(state.calls).not.toContain('/api/access-grants/my-requests');
  });

  it('Publish lists owned assets with gaps and offers a review request', async () => {
    applyJourneyRole();
    renderWithProviders(<Home />);
    const list = await screen.findByTestId('essentials-publish-gaps');
    expect(within(list).getByText('customers')).toHaveAttribute('href', '/assets/a2');
    expect(within(list).queryByText('orders')).not.toBeInTheDocument();
    expect(within(list).getByText('No description')).toBeInTheDocument();
    expect(within(list).getByText('Not reviewed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Request a review/ })).toBeInTheDocument();
  });

  it('Publish loads my assets in one call per page, sized by the saved preference', async () => {
    owned = Array.from({ length: 30 }, (_, i) => ({
      id: `m${i}`, name: `table_${i}`, location: `main.s.t${i}`, description: '',
    }));
    useEssentialsHomePreferencesStore.setState({ publishPageSize: 25 });
    applyJourneyRole();
    renderWithProviders(<Home />);
    const paging = await screen.findByTestId('essentials-publish-paging');
    expect(within(paging).getByText('Showing 25 of your 30 assets.')).toBeInTheDocument();
    expect(state.calls).toContain('/api/assets?owned_by_me=true&skip=0&limit=25');
    expect(state.calls.some((u) => /^\/api\/assets\/m\d/.test(u))).toBe(false);
    expect(within(paging).getByRole('combobox', { name: 'Per page' })).toHaveTextContent('25');

    await act(async () => {
      within(paging).getByRole('button', { name: 'Load more' }).click();
    });
    await waitFor(() =>
      expect(within(paging).getByText('Showing 30 of your 30 assets.')).toBeInTheDocument(),
    );
    expect(state.calls).toContain('/api/assets?owned_by_me=true&skip=25&limit=25');
    expect(within(paging).queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
    expect(within(screen.getByTestId('essentials-publish-gaps')).getAllByText('No description'))
      .toHaveLength(30);
  });

  it('a new page size starts over from the first page', async () => {
    owned = Array.from({ length: 12 }, (_, i) => ({
      id: `m${i}`, name: `table_${i}`, location: `main.s.t${i}`, description: '',
    }));
    applyJourneyRole();
    renderWithProviders(<Home />);
    const paging = await screen.findByTestId('essentials-publish-paging');
    expect(within(paging).getByText('Showing 10 of your 12 assets.')).toBeInTheDocument();
    act(() => useEssentialsHomePreferencesStore.getState().setPublishPageSize(50));
    // The page reloads from the first page, so the paging row is rendered again.
    expect(await screen.findByText('Showing 12 of your 12 assets.')).toBeInTheDocument();
    expect(state.calls).toContain('/api/assets?owned_by_me=true&skip=0&limit=50');
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('says only the loaded assets are clean while more pages exist', async () => {
    owned = Array.from({ length: 11 }, (_, i) => ({
      id: `m${i}`, name: `table_${i}`, location: `main.s.t${i}`, description: 'ok',
    }));
    state.routes['/api/data-asset-reviews'] = [review('rx', 'approved', 'a@x.com', 'b@x.com',
      owned.map((a) => ({ fqn: a.location, status: 'approved', at: '2026-01-01' })))];
    applyJourneyRole();
    renderWithProviders(<Home />);
    expect(await screen.findByText('No gaps in the assets loaded so far.')).toBeInTheDocument();
  });

  it('Maintain shows my pending requests and my open reviews', async () => {
    applyJourneyRole();
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

  it('counts my tables below the first maturity level and links to each one', async () => {
    state.routes['/api/assets?below_first_maturity_level=true'] = {
      items: [{ id: 'a3', name: 'pedidos_diarios' }, { id: 'a4', name: 'entregas' }],
      total: 7, skip: 0, limit: 5,
    };
    applyJourneyRole();
    await i18n.changeLanguage('pt');
    try {
      renderWithProviders(<Home />);
      const card = screen.getByTestId('essentials-section-maturity');
      expect(within(card).getByText('Tabelas abaixo do primeiro nível')).toBeInTheDocument();
      expect(await within(card).findByTestId('essentials-maturity-count')).toHaveTextContent('7');
      expect(within(card).getByText('pedidos_diarios')).toHaveAttribute('href', '/assets/a3');
      expect(within(card).getByText('entregas')).toHaveAttribute('href', '/assets/a4');
      expect(within(card).getByText('Mostrando 2 de 7.')).toBeInTheDocument();
    } finally {
      await i18n.changeLanguage('en');
    }
    const call = state.calls.find((u) => u.includes('below_first_maturity_level'));
    const q = new URL(call!, 'http://x').searchParams;
    expect(q.get('owned_by_me')).toBe('true');
    expect(q.get('limit')).toBe('5');
  });

  it('says none of my tables is below the first level when the list is empty', async () => {
    state.routes['/api/assets?below_first_maturity_level=true'] = {
      items: [], total: 0, skip: 0, limit: 5,
    };
    applyJourneyRole();
    renderWithProviders(<Home />);
    const card = screen.getByTestId('essentials-section-maturity');
    expect(await within(card).findByText(
      'None of your evaluated tables is below the first level.',
    )).toBeInTheDocument();
    expect(within(card).getByTestId('essentials-maturity-count')).toHaveTextContent('0');
    expect(within(card).queryByTestId('essentials-maturity-list')).not.toBeInTheDocument();
  });

  it('shows an error instead of a zero count when the card fails to load', async () => {
    // No route for the below-first-level call: the fetch answers 404.
    applyJourneyRole();
    renderWithProviders(<Home />);
    const card = screen.getByTestId('essentials-section-maturity');
    expect(await within(card).findByTestId('essentials-maturity-error')).toHaveTextContent(
      "Couldn't load your tables below the first level.",
    );
    expect(within(card).queryByTestId('essentials-maturity-count')).not.toBeInTheDocument();
    expect(within(card).queryByText(
      'None of your evaluated tables is below the first level.',
    )).not.toBeInTheDocument();
  });

  it('a user whose groups match a role with the journey section gets the journey home', () => {
    state.roles = [{
      id: 'consumers', name: 'Consumers', home_sections: [HomeSection.JOURNEY],
      assigned_groups: ['consumers'],
    }];
    useUserStore.setState({
      userInfo: { email: 'me@x.com', username: 'me', user: 'me', ip: null,
        groups: ['consumers'] } as any,
    });
    renderWithProviders(<Home />);
    expect(screen.getByTestId('essentials-home')).toBeInTheDocument();
    expect(screen.queryByText('Overview')).not.toBeInTheDocument();
  });

  it('a role without the journey section keeps the Full home', () => {
    applyJourneyRole([HomeSection.DISCOVERY]);
    renderWithProviders(<Home />);
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.queryByTestId('essentials-home')).not.toBeInTheDocument();
  });

  it('a hidden feature gets no journey section or link, but its access is unchanged', async () => {
    applyJourneyRole();
    state.hidden = ['assets'];
    renderWithProviders(<Home />);
    expect(screen.queryByTestId('essentials-section-publish')).not.toBeInTheDocument();
    expect(screen.queryByTestId('essentials-publish-gaps')).not.toBeInTheDocument();
    expect(screen.getByTestId('essentials-section-understand')).toBeInTheDocument();
    expect(within(screen.getByTestId('essentials-section-understand')).queryByText('Assets'))
      .not.toBeInTheDocument();
    expect(state.calls.some((u) => u.includes('owned_by_me'))).toBe(false);
    expect(state.calls).not.toContain('/api/assets?limit=1');
  });
});

describe('Essentials home preferences', () => {
  it('keeps only the offered page sizes', () => {
    const { setPublishPageSize } = useEssentialsHomePreferencesStore.getState();
    setPublishPageSize(50);
    expect(useEssentialsHomePreferencesStore.getState().publishPageSize).toBe(50);
    setPublishPageSize(7);
    expect(useEssentialsHomePreferencesStore.getState().publishPageSize).toBe(10);
    setPublishPageSize(25);
    expect(JSON.parse(localStorage.getItem('essentials-home-preferences') || '{}').state)
      .toEqual({ publishPageSize: 25 });
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
