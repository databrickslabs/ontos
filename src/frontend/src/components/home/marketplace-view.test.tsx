import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { useViewModeStore } from '@/stores/view-mode-store';

const DOMAINS = [
  { id: 'retail', name: 'Retail', parent_id: null },
  { id: 'retail-ops', name: 'Retail Operations', parent_id: 'retail' },
  { id: 'retail-web', name: 'Retail Web', parent_id: 'retail' },
  { id: 'finance', name: 'Finance', parent_id: null },
];

vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({
    domains: DOMAINS,
    loading: false,
    getDomainName: (id: string) => DOMAINS.find(d => d.id === id)?.name ?? id,
  }),
}));

// The graph itself is covered in data-domain-mini-graph.test.tsx: stand in a stub that shows
// the focused domain and lets a test click a node.
vi.mock('@/components/data-domains/data-domain-mini-graph', () => ({
  DataDomainMiniGraph: ({ currentDomain, onNodeClick }: {
    currentDomain: { id: string };
    onNodeClick: (id: string) => void;
  }) => (
    <div>
      <span data-testid="graph-focus">{currentDomain.id}</span>
      <button onClick={() => onNodeClick('retail-ops')}>node-retail-ops</button>
    </div>
  ),
}));

vi.mock('@/components/quality/quality-badge', () => ({
  QualityBadge: () => <span>quality</span>,
}));

// The real dialog fetches metadata and ratings; here only the header slot matters.
vi.mock('@/components/metadata/entity-info-dialog', () => ({
  default: ({ headerExtra }: { headerExtra?: React.ReactNode }) => (
    <div data-testid="info-dialog-extra">{headerExtra}</div>
  ),
}));

const PRODUCTS = [
  {
    id: 'p1', name: 'Customer 360', status: 'active', domain: 'Retail', domain_ids: ['retail'],
    publication_scope: 'organization', certification_level: 1,
    description: { purpose: 'Everything about shoppers' },
    team: {
      name: 'Retail Team',
      members: [{ username: 'ana.silva@example.com', name: 'Ana Silva', role: 'owner' }],
    },
  },
  {
    id: 'p2', name: 'Orders', status: 'draft', domain: 'Finance', domain_ids: ['finance'],
    publication_scope: 'domain',
    description: { purpose: 'Order lines' },
    team: { members: [{ username: 'joao.souza@example.com' }] },
  },
  {
    id: 'p3', name: 'Legacy Sales', status: 'deprecated', domain: 'Retail',
    domain_ids: ['retail-ops'],
    publication_scope: 'organization', replacement_product_id: 'p1',
    description: { purpose: 'Old sales' },
    owner_team_name: 'Sales Team',
  },
  {
    id: 'p4', name: 'Old Feed', status: 'deprecated', domain: 'Finance', domain_ids: ['finance'],
    publication_scope: 'organization', description: { purpose: 'Retired feed' },
  },
];

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

let searchResponse: unknown[] = [];
let fetchMock: MockInstance<typeof fetch>;

const cardTitleEls = () =>
  Array.from(document.querySelectorAll<HTMLElement>('.text-base.truncate'));

async function renderMarketplace() {
  const { default: MarketplaceView } = await import('./marketplace-view');
  renderWithProviders(<MarketplaceView />);
  await screen.findByText('Customer 360');
}

describe('MarketplaceView', () => {
  beforeEach(() => {
    // Radix Select needs these in jsdom
    Element.prototype.hasPointerCapture ??= () => false;
    Element.prototype.releasePointerCapture ??= () => {};
    Element.prototype.scrollIntoView ??= () => {};
    searchResponse = [];
    useViewModeStore.setState({ domainBrowserStyle: 'pills' });
    fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith('/api/data-products/published')) return jsonResponse(PRODUCTS);
      if (url.startsWith('/api/search')) return jsonResponse(searchResponse);
      if (url.startsWith('/api/certification-levels')) {
        return jsonResponse([{ level_order: 1, name: 'Gold', color: 'amber', icon: 'shield' }]);
      }
      if (url.startsWith('/api/data-domains/')) {
        const id = url.split('/').pop()!;
        return jsonResponse(DOMAINS.find(d => d.id === id));
      }
      return jsonResponse([]);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('search (#1599)', () => {
    it('asks the server; keeps only hits in the marketplace listing, in rank order', async () => {
      searchResponse = [
        { id: 'product::p2', type: 'data-product' },
        { id: 'glossary::x', type: 'glossary-term' },
        { id: 'product::hidden', type: 'data-product' }, // not in the listing: never shown
        { id: 'product::p1', type: 'data-product' },
      ];
      await renderMarketplace();
      await userEvent.type(screen.getByPlaceholderText(/help you find/i), 'customer');

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith(
          '/api/search?search_term=customer&types=data-product', expect.anything(),
        );
      });
      // "Orders" matches no text of the query: the server decided (e.g. a linked concept)
      await waitFor(() => expect(screen.queryByText('Legacy Sales')).not.toBeInTheDocument());
      const titles = cardTitleEls().map(h => h.textContent);
      expect(titles).toEqual(['Orders', 'Customer 360']);
    });

    it('drops the previous query hits while the next query is loading', async () => {
      searchResponse = [{ id: 'product::p1', type: 'data-product' }];
      await renderMarketplace();
      const box = screen.getByPlaceholderText(/help you find/i);
      await userEvent.type(box, 'customer');
      await waitFor(() => expect(cardTitleEls().map(e => e.textContent)).toEqual(['Customer 360']));

      // The next request never answers: the old hits must not stay up as its results
      fetchMock.mockImplementation(async (input) => {
        if (String(input).startsWith('/api/search')) return new Promise<Response>(() => {});
        return jsonResponse([]);
      });
      await userEvent.type(box, 's');
      await waitFor(() => expect(screen.queryByText('Customer 360')).not.toBeInTheDocument());
    });

    it('clears the search error as soon as the query changes', async () => {
      await renderMarketplace();
      fetchMock.mockImplementation(async (input) => {
        if (String(input).startsWith('/api/search')) return new Response('x', { status: 500 });
        return jsonResponse([]);
      });
      const box = screen.getByPlaceholderText(/help you find/i);
      await userEvent.type(box, 'abc');
      expect(await screen.findByText('Search is unavailable right now.')).toBeInTheDocument();
      fetchMock.mockImplementation(async (input) => {
        if (String(input).startsWith('/api/search')) return new Promise<Response>(() => {});
        return jsonResponse([]);
      });
      await userEvent.type(box, 'd');
      await waitFor(() => {
        expect(screen.queryByText('Search is unavailable right now.')).not.toBeInTheDocument();
      });
    });

    it('does not filter in the browser while the server has not answered', async () => {
      await renderMarketplace();
      fetchMock.mockImplementation(async (input) => {
        if (String(input).startsWith('/api/search')) return new Promise<Response>(() => {});
        return jsonResponse([]);
      });
      await userEvent.type(screen.getByPlaceholderText(/help you find/i), 'Orders');
      // A browser-side substring match would already show it
      expect(screen.queryByText('Orders')).not.toBeInTheDocument();
    });
  });

  describe('cards (#1600)', () => {
    it('shows a person, never an email, and one trust badge, no raw status or scope', async () => {
      await renderMarketplace();
      expect(screen.getByText(/Ana Silva/)).toBeInTheDocument();
      expect(screen.getByText(/Owner: Sales Team/)).toBeInTheDocument();
      expect(document.body.textContent).not.toMatch(/@example\.com/);
      expect(document.body.textContent).not.toMatch(/joao\.souza/);

      const cards = cardTitleEls().map(h => h.closest('.cursor-pointer')!);
      const [customer, orders, legacy] = cards as HTMLElement[];
      expect(within(customer).getByText('Gold')).toBeInTheDocument();
      expect(within(customer).queryByText('active')).not.toBeInTheDocument();
      expect(within(customer).queryByText(/organization/i)).not.toBeInTheDocument();
      expect(within(orders).getByText('Preview')).toBeInTheDocument();
      expect(within(orders).queryByText('draft')).not.toBeInTheDocument();
      expect(within(orders).getByText(/Owner: Unknown/)).toBeInTheDocument();
      // One retiring mention: the line with the replacement, else the badge
      expect(within(legacy).getByText('Retiring, use Customer 360 instead')).toBeInTheDocument();
      expect(within(legacy).queryByText('Retiring')).not.toBeInTheDocument();
      const oldFeed = cardTitleEls()
        .find(e => e.textContent === 'Old Feed')!.closest('.cursor-pointer')!;
      expect(within(oldFeed as HTMLElement).getByText('Retiring')).toBeInTheDocument();
      expect(within(legacy).queryByText('deprecated')).not.toBeInTheDocument();
    });

    it('shows status and scope in the product info dialog, not on the card', async () => {
      await renderMarketplace();
      await userEvent.click(screen.getByText('Orders'));
      const extra = await screen.findByTestId('info-dialog-extra');
      expect(within(extra).getByText('Status: Draft')).toBeInTheDocument();
      expect(within(extra).getByText('Published to: Domain')).toBeInTheDocument();
      expect(within(extra).getByText('quality')).toBeInTheDocument();
    });

    it('hides "Exact match only" until Advanced filters is opened', async () => {
      await renderMarketplace();
      await userEvent.click(screen.getByRole('button', { name: 'Retail' }));
      expect(screen.queryByText('Exact match only')).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: /advanced filters/i }));
      expect(screen.getByText('Exact match only')).toBeInTheDocument();
    });
  });

  describe('graph view (#1588, #1589, #1591)', () => {
    beforeEach(() => {
      useViewModeStore.setState({ domainBrowserStyle: 'graph' });
    });

    it('shows the active filter and clears it from the header', async () => {
      await renderMarketplace();
      await userEvent.click(await screen.findByText('node-retail-ops'));

      const chips = await screen.findByTestId('marketplace-active-domains');
      expect(within(chips).getByText('Retail Operations')).toBeInTheDocument();
      expect(screen.queryByText('Customer 360')).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'All Domains' }));
      expect(screen.queryByTestId('marketplace-active-domains')).not.toBeInTheDocument();
      expect(await screen.findByText('Customer 360')).toBeInTheDocument();
      expect(screen.getByText('Orders')).toBeInTheDocument();
    });

    it('reaches another root domain through the root switcher', async () => {
      await renderMarketplace();
      await userEvent.click(screen.getByRole('combobox', { name: /top-level domain/i }));
      await userEvent.click(await screen.findByRole('option', { name: 'Finance' }));
      await waitFor(() => expect(screen.getByTestId('graph-focus')).toHaveTextContent('finance'));
      expect(await screen.findByText('Orders')).toBeInTheDocument();
      expect(screen.queryByText('Customer 360')).not.toBeInTheDocument();
    });

    it('focuses the selected domain when entering graph mode from pills', async () => {
      useViewModeStore.setState({ domainBrowserStyle: 'pills' });
      await renderMarketplace();
      await userEvent.click(screen.getByRole('button', { name: 'Retail Operations' }));
      await userEvent.click(screen.getByRole('button', { name: 'Retail Web' }));
      act(() => useViewModeStore.setState({ domainBrowserStyle: 'graph' }));
      // two siblings: their nearest common ancestor
      await waitFor(() => expect(screen.getByTestId('graph-focus')).toHaveTextContent('retail'));
      expect(screen.getByTestId('graph-focus')).not.toHaveTextContent('retail-ops');
    });
  });
});
