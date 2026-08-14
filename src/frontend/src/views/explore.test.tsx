import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import type { OntologyConcept } from '@/types/ontology';

// ---------------------------------------------------------------------------
// Unified Explore surface tests.
//
// We stub the render engines (ConceptsTab / GraphTab) and the filter panel so
// we can assert wiring, not engine internals:
//  - the filter panel renders,
//  - all three view-mode options render,
//  - switching mode swaps List/Tree (ConceptsTab) <-> Graph (GraphTab),
//  - the SAME filteredConcepts is handed to every mode,
//  - the legacy ?concept= deep link redirects to the detail route.
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: any) => {
      if (typeof options === 'string') return options;
      if (options && typeof options === 'object' && 'defaultValue' in options) {
        return options.defaultValue as string;
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ hasPermission: () => true, fetchPermissions: vi.fn(), fetchAvailableRoles: vi.fn() }),
}));

vi.mock('@/stores/breadcrumb-store', () => ({ default: () => () => undefined }));

vi.mock('@/stores/knowledge-graph-store', () => ({
  useKnowledgeGraphStore: (selector: any) =>
    selector({ refreshNonce: 0, lastReason: null, bumpRefreshNonce: vi.fn() }),
}));

// Spy so the ?source= deep-link test can assert a single idempotent set.
const setHiddenSourcesSpy = vi.fn();
vi.mock('@/stores/glossary-preferences-store', () => ({
  useGlossaryPreferencesStore: () => ({
    hiddenSources: [],
    groupByDimension: 'none',
    groupBySource: false,
    showProperties: false,
    groupByDomain: false,
    isFilterExpanded: false,
    toggleSource: vi.fn(),
    setHiddenSources: setHiddenSourcesSpy,
    selectAllSources: vi.fn(),
    selectNoneSources: vi.fn(),
    setGroupByDimension: vi.fn(),
    setShowProperties: vi.fn(),
    setFilterExpanded: vi.fn(),
  }),
}));

// availableSources is overridable per-test so the ?source= path has real sources.
let availableSourcesMock: string[] = [];

// A stable filtered selection returned by the single source-of-truth hook.
const FILTERED: OntologyConcept[] = [
  { iri: 'urn:a', label: 'A', concept_type: 'concept' } as unknown as OntologyConcept,
  { iri: 'urn:b', label: 'B', concept_type: 'concept' } as unknown as OntologyConcept,
];

vi.mock('@/hooks/use-explore-concepts', () => ({
  useExploreConcepts: () => ({
    isLoading: false,
    collections: [],
    groupedConcepts: {},
    groupedProperties: {},
    stats: null,
    availableSources: availableSourcesMock,
    sourceConceptCounts: {},
    filteredConcepts: FILTERED,
    totalConcepts: FILTERED.length,
    totalProperties: 0,
    refetch: vi.fn(),
  }),
}));

// Engine stubs record which filteredConcepts they receive.
let conceptsTabConcepts: OntologyConcept[] | null = null;
let conceptsTabViewMode: string | null = null;
let graphTabConcepts: OntologyConcept[] | null = null;

vi.mock('@/components/knowledge', () => ({
  ConceptsTab: ({ filteredConcepts, viewMode }: { filteredConcepts: OntologyConcept[]; viewMode?: string }) => {
    conceptsTabConcepts = filteredConcepts;
    conceptsTabViewMode = viewMode ?? null;
    return <div data-testid="concepts-tab">{filteredConcepts.length} concepts</div>;
  },
  GraphTab: ({ concepts }: { concepts: OntologyConcept[] }) => {
    graphTabConcepts = concepts;
    return <div data-testid="graph-tab">{concepts.length} nodes</div>;
  },
  GlossaryFilterPanel: () => <div data-testid="filter-panel" />,
  CollectionEditorDialog: () => null,
  ConceptEditorDialog: () => null,
  ImportConceptsDialog: () => null,
}));

import ExploreView from './explore';

beforeEach(() => {
  conceptsTabConcepts = null;
  conceptsTabViewMode = null;
  graphTabConcepts = null;
  availableSourcesMock = [];
  setHiddenSourcesSpy.mockClear();
  global.fetch = vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({}), text: async () => '',
  })) as unknown as typeof fetch;
});

function renderExplore(initialEntry = '/concepts/browser') {
  let observed = { pathname: '', search: '' };
  function Probe() {
    const location = useLocation();
    observed = { pathname: location.pathname, search: location.search };
    return null;
  }
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/concepts/browser" element={<><ExploreView /><Probe /></>} />
        <Route path="/concepts/browser/:iri" element={<><div data-testid="detail-route" /><Probe /></>} />
      </Routes>
    </MemoryRouter>,
  );
  return () => observed;
}

describe('Explore unified surface', () => {
  it('renders the filter panel and all three view-mode options', () => {
    renderExplore();
    expect(screen.getByTestId('filter-panel')).toBeInTheDocument();
    const tabs = screen.getAllByRole('tab');
    const labels = tabs.map((el) => el.textContent);
    expect(labels).toEqual(expect.arrayContaining(['List', 'Tree', 'Graph']));
  });

  it('defaults to List (ConceptsTab) and passes the shared filteredConcepts', () => {
    renderExplore();
    expect(screen.getByTestId('concepts-tab')).toBeInTheDocument();
    expect(screen.queryByTestId('graph-tab')).not.toBeInTheDocument();
    expect(conceptsTabConcepts).toEqual(FILTERED);
  });

  it('passes viewMode="list" to ConceptsTab by default', () => {
    renderExplore();
    expect(conceptsTabViewMode).toBe('list');
  });

  it('passes viewMode="tree" to ConceptsTab when ?view=tree', () => {
    renderExplore('/concepts/browser?view=tree');
    expect(conceptsTabViewMode).toBe('tree');
  });

  it('switching to Graph swaps to GraphTab with the SAME filteredConcepts', async () => {
    renderExplore();
    const graphTab = screen.getByRole('tab', { name: /Graph/ });
    fireEvent.click(graphTab);
    await waitFor(() => expect(screen.getByTestId('graph-tab')).toBeInTheDocument());
    expect(screen.queryByTestId('concepts-tab')).not.toBeInTheDocument();
    expect(graphTabConcepts).toEqual(FILTERED);
  });

  it('Tree mode still renders through ConceptsTab (shared selection)', async () => {
    renderExplore();
    fireEvent.click(screen.getByRole('tab', { name: /Tree/ }));
    await waitFor(() => expect(screen.getByTestId('concepts-tab')).toBeInTheDocument());
    expect(conceptsTabConcepts).toEqual(FILTERED);
    expect(conceptsTabViewMode).toBe('tree');
  });

  it('applies ?source= as ONE hidden-set and consumes the param (no toggle loop)', async () => {
    // Regression: the ?source= effect used to toggle sources one-by-one and
    // depend on hiddenSources, so each toggle re-fired it — an infinite loop
    // that froze the page. It must now hide-all-but-target in a single set and
    // consume the param so it can't re-fire.
    availableSourcesMock = ['e2e-author', 'finance', 'logistics'];
    const observe = renderExplore('/concepts/browser?source=urn%3Aglossary%3Ae2e-author');
    await waitFor(() => {
      // Target shown, the other two hidden — in exactly one call.
      expect(setHiddenSourcesSpy).toHaveBeenCalledWith(
        expect.arrayContaining(['finance', 'logistics']),
      );
    });
    expect(setHiddenSourcesSpy).toHaveBeenCalledTimes(1);
    expect(setHiddenSourcesSpy.mock.calls[0][0]).not.toContain('e2e-author');
    // The param is consumed so the effect cannot re-fire on it.
    await waitFor(() => expect(observe().search).not.toContain('source='));
  });

  it('redirects legacy ?concept=IRI to /concepts/browser/:iri', async () => {
    const iri = 'https://example.org/onto#Customer';
    const observe = renderExplore(`/concepts/browser?concept=${encodeURIComponent(iri)}`);
    await waitFor(() => {
      expect(observe().pathname).toBe(`/concepts/browser/${encodeURIComponent(iri)}`);
    });
  });
});
