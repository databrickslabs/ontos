import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ConceptTooltip, type ConceptMatch } from './concept-tooltip';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

// ---- helpers ----

const PERSON_MATCH: ConceptMatch = {
  concept: {
    iri: 'urn:glossary:Person',
    label: 'Person',
    comment: 'A human being in the domain model.',
    concept_type: 'class',
    source_context: 'enterprise-glossary',
  },
  relevance_score: 1.0,
  match_type: 'label',
};

const PRODUCT_MATCH: ConceptMatch = {
  concept: {
    iri: 'urn:glossary:Product',
    label: 'Product',
    comment: 'A sellable item.',
    concept_type: 'class',
  },
  relevance_score: 0.8,
  match_type: 'label',
};

function mockFetchOk(results: ConceptMatch[]) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ results }),
  });
}

function mockFetchEmpty() {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ results: [] }),
  });
}

function mockFetchError() {
  return vi.fn().mockRejectedValue(new Error('Network error'));
}

function mockFetchHttpError() {
  return vi.fn().mockResolvedValue({ ok: false, status: 500 });
}

function renderTooltip(nodeType: string | null) {
  return render(
    <MemoryRouter>
      <ConceptTooltip nodeType={nodeType} />
    </MemoryRouter>,
  );
}

describe('ConceptTooltip', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  // ---- Rendering ----

  it('renders nothing when nodeType is null', () => {
    const { container } = renderTooltip(null);
    expect(container.innerHTML).toBe('');
  });

  it('renders matches when API returns results', async () => {
    globalThis.fetch = mockFetchOk([PERSON_MATCH]);
    renderTooltip('Person');

    await waitFor(() => {
      expect(screen.getByTestId('concept-tooltip')).toBeInTheDocument();
    });
    expect(screen.getByText('Person')).toBeInTheDocument();
    expect(screen.getByText('A human being in the domain model.')).toBeInTheDocument();
    expect(screen.getByText('class')).toBeInTheDocument();
  });

  it('renders nothing when API returns empty results', async () => {
    globalThis.fetch = mockFetchEmpty();
    const { container } = renderTooltip('UnknownType');

    // Wait for fetch to complete (loading state disappears)
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    });

    // After fetch, no tooltip should render
    expect(container.querySelector('[data-testid="concept-tooltip"]')).toBeNull();
  });

  it('renders multiple matches', async () => {
    globalThis.fetch = mockFetchOk([PERSON_MATCH, PRODUCT_MATCH]);
    renderTooltip('SomeType');

    await waitFor(() => {
      expect(screen.getByTestId('concept-tooltip')).toBeInTheDocument();
    });
    expect(screen.getByText('Person')).toBeInTheDocument();
    expect(screen.getByText('Product')).toBeInTheDocument();
  });

  it('shows "View in Glossary" link pointing to /semantic-models', async () => {
    globalThis.fetch = mockFetchOk([PERSON_MATCH]);
    renderTooltip('Person');

    await waitFor(() => {
      expect(screen.getByTestId('concept-tooltip')).toBeInTheDocument();
    });

    const links = screen.getAllByText('conceptTooltip.viewInGlossary');
    expect(links.length).toBe(1);
    const link = links[0].closest('a');
    expect(link).toHaveAttribute('href', '/semantic-models');
  });

  it('falls back to IRI when label is missing', async () => {
    const noLabelMatch: ConceptMatch = {
      ...PERSON_MATCH,
      concept: { ...PERSON_MATCH.concept, label: undefined },
    };
    globalThis.fetch = mockFetchOk([noLabelMatch]);
    renderTooltip('Person');

    await waitFor(() => {
      expect(screen.getByTestId('concept-tooltip')).toBeInTheDocument();
    });
    expect(screen.getByText('urn:glossary:Person')).toBeInTheDocument();
  });

  // ---- Caching ----

  it('caches results — second render with same type skips API call', async () => {
    const mockFetch = mockFetchOk([PERSON_MATCH]);
    globalThis.fetch = mockFetch;

    const { rerender } = render(
      <MemoryRouter>
        <ConceptTooltip nodeType="Person" />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('concept-tooltip')).toBeInTheDocument();
    });
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Re-render with null, then back to same type
    rerender(
      <MemoryRouter>
        <ConceptTooltip nodeType={null} />
      </MemoryRouter>,
    );
    rerender(
      <MemoryRouter>
        <ConceptTooltip nodeType="Person" />
      </MemoryRouter>,
    );

    // Should still be 1 call — cache hit
    await waitFor(() => {
      expect(screen.getByTestId('concept-tooltip')).toBeInTheDocument();
    });
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  // ---- Error handling ----

  it('renders nothing when fetch throws a network error', async () => {
    globalThis.fetch = mockFetchError();
    const { container } = renderTooltip('Person');

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    });
    expect(container.querySelector('[data-testid="concept-tooltip"]')).toBeNull();
  });

  it('renders nothing when API returns non-OK status', async () => {
    globalThis.fetch = mockFetchHttpError();
    const { container } = renderTooltip('Person');

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    });
    expect(container.querySelector('[data-testid="concept-tooltip"]')).toBeNull();
  });

  // ---- API call shape ----

  it('calls the correct API endpoint with q and limit params', async () => {
    const mockFetch = mockFetchOk([PERSON_MATCH]);
    globalThis.fetch = mockFetch;
    renderTooltip('Person');

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    const calledUrl = mockFetch.mock.calls[0][0] as string;
    expect(calledUrl).toContain('/api/semantic-models/search');
    expect(calledUrl).toContain('q=Person');
    expect(calledUrl).toContain('limit=3');
  });
});
