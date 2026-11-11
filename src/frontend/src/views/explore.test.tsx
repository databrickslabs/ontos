import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
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

// Stable spy so the breadcrumb effect does not loop and its segments can be asserted.
const setStaticSegmentsSpy = vi.fn();
vi.mock('@/stores/breadcrumb-store', () => ({
  default: (selector: any) => selector({ setStaticSegments: setStaticSegmentsSpy }),
}));

vi.mock('@/stores/knowledge-graph-store', () => ({
  useKnowledgeGraphStore: (selector: any) =>
    selector({ refreshNonce: 0, lastReason: null, bumpRefreshNonce: vi.fn() }),
}));

// Spy so the ?source= deep-link test can assert a single idempotent set.
const setHiddenSourcesSpy = vi.fn();
vi.mock('@/stores/glossary-preferences-store', () => ({
  useGlossaryPreferencesStore: () => ({
    hiddenSources: hiddenSourcesMock,
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
// Collections are overridable per-test for the scheme-aware Create menu.
let collectionsMock: any[] = [];
// Hidden sources are overridable per-test (source filter narrows the focus).
let hiddenSourcesMock: string[] = [];
// Grouped concepts before user filters; empty means "nothing to explore yet".
let groupedConceptsMock: Record<string, unknown[]> = {};

// Simple/Advanced mode, controllable per test.
let modeMock: 'simple' | 'advanced' = 'simple';
vi.mock('@/components/concepts/mode-switch', () => ({
  useConceptMode: () => [modeMock, vi.fn()],
  ConceptModeSwitch: () => null,
}));

vi.mock('@/components/search/kg-search', () => ({
  default: () => <div data-testid="kg-search" />,
}));

// Inline stand-in for the Radix dropdown: always renders its items as buttons
// (driving Radix pointer/portal machinery in jsdom is flaky in CI).
vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="create-menu">{children}</div>
  ),
  DropdownMenuItem: ({ children, onClick }: { children?: React.ReactNode; onClick?: () => void }) => (
    <button type="button" role="menuitem" onClick={onClick}>{children}</button>
  ),
  DropdownMenuSeparator: () => <hr data-testid="menu-separator" />,
}));

// A stable filtered selection returned by the single source-of-truth hook.
const FILTERED: OntologyConcept[] = [
  { iri: 'urn:a', label: 'A', concept_type: 'concept' } as unknown as OntologyConcept,
  { iri: 'urn:b', label: 'B', concept_type: 'concept' } as unknown as OntologyConcept,
];

vi.mock('@/hooks/use-explore-concepts', async () => ({
  // Keep the real session store / query helper; only the data hook is stubbed.
  ...(await vi.importActual<typeof import('@/hooks/use-explore-concepts')>('@/hooks/use-explore-concepts')),
  useExploreConcepts: () => ({
    isLoading: false,
    collections: collectionsMock,
    groupedConcepts: groupedConceptsMock,
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
let editorProps: any = null;
let schemeEditorProps: any = null;

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
  GlossaryFilterPanel: ({
    showSystemSources,
    onSetShowSystemSources,
  }: {
    showSystemSources?: boolean;
    onSetShowSystemSources?: (enabled: boolean) => void;
  }) => (
    <div data-testid="filter-panel">
      <button
        data-testid="system-toggle"
        data-checked={String(!!showSystemSources)}
        onClick={() => onSetShowSystemSources?.(!showSystemSources)}
      />
    </div>
  ),
  CollectionEditorDialog: (props: any) => {
    schemeEditorProps = props;
    return null;
  },
  ConceptEditorDialog: (props: any) => {
    editorProps = props;
    return null;
  },
}));

import ExploreView from './explore';
import { useExploreSessionStore, systemSourcesQuery } from '@/hooks/use-explore-concepts';

beforeEach(() => {
  conceptsTabConcepts = null;
  conceptsTabViewMode = null;
  graphTabConcepts = null;
  availableSourcesMock = [];
  collectionsMock = [];
  hiddenSourcesMock = [];
  groupedConceptsMock = { 'my-scheme': FILTERED };
  modeMock = 'simple';
  editorProps = null;
  schemeEditorProps = null;
  useExploreSessionStore.setState({ showSystemSources: false });
  setHiddenSourcesSpy.mockClear();
  setStaticSegmentsSpy.mockClear();
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
        <Route path="/concepts/browser/*" element={<><div data-testid="detail-route" /><Probe /></>} />
        <Route path="/concepts/define" element={<><div data-testid="define-route" /><Probe /></>} />
      </Routes>
    </MemoryRouter>,
  );
  return () => observed;
}

describe('Explore unified surface', () => {
  it('sets breadcrumbs to Concepts > Explore', () => {
    renderExplore();
    expect(setStaticSegmentsSpy).toHaveBeenCalledWith([
      { label: 'Concepts', path: '/concepts' },
      { label: 'Explore', path: '/concepts/browser' },
    ]);
  });

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

  it('wires the "Show system ontologies" toggle in Advanced: default OFF, session store flips on click', async () => {
    modeMock = 'advanced';
    renderExplore();
    const toggle = screen.getByTestId('system-toggle');
    expect(toggle).toHaveAttribute('data-checked', 'false');
    expect(useExploreSessionStore.getState().showSystemSources).toBe(false);
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByTestId('system-toggle')).toHaveAttribute('data-checked', 'true'));
    expect(useExploreSessionStore.getState().showSystemSources).toBe(true);
  });

  it('does not pass the "Show system ontologies" setter in Simple mode', () => {
    useExploreSessionStore.setState({ showSystemSources: true });
    renderExplore();
    fireEvent.click(screen.getByTestId('system-toggle'));
    // The stub calls the setter only when it is passed; the store is unchanged.
    expect(useExploreSessionStore.getState().showSystemSources).toBe(true);
  });

  it('has no Upload / Import button (upload lives on Define)', () => {
    modeMock = 'advanced';
    renderExplore();
    expect(screen.queryByTitle('common:actions.import')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Import|Upload/i })).not.toBeInTheDocument();
  });

  it('system-sources query helper only opts in when the toggle is on', () => {
    expect(systemSourcesQuery(false)).toBe('');
    expect(systemSourcesQuery(true)).toBe('?include_system=true');
  });

  it('redirects legacy ?concept=IRI to /concepts/browser/:iri', async () => {
    const iri = 'https://example.org/onto#Customer';
    const observe = renderExplore(`/concepts/browser?concept=${encodeURIComponent(iri)}`);
    await waitFor(() => {
      expect(observe().pathname).toBe(`/concepts/browser/${encodeURIComponent(iri)}`);
    });
  });
});

const ONTOLOGY = { iri: 'urn:ontology:core', label: 'Core', collection_type: 'ontology', is_editable: true };
const TAXONOMY = { iri: 'urn:taxonomy:regions', label: 'Regions', collection_type: 'taxonomy', is_editable: true };
const GLOSSARY = { iri: 'urn:glossary:business', label: 'Business', collection_type: 'glossary', is_editable: true };

function menuLabels() {
  return screen.getAllByRole('menuitem').map((el) => el.textContent);
}

describe('Explore Create menu adapts to the scheme in focus', () => {
  it('glossary in focus: New Term, then New Concept Scheme', () => {
    collectionsMock = [GLOSSARY];
    renderExplore();
    expect(menuLabels()).toEqual(['New Term', 'New Concept Scheme']);
  });

  it('taxonomy in focus: New Concept', () => {
    collectionsMock = [TAXONOMY];
    renderExplore();
    expect(menuLabels()).toEqual(['New Concept', 'New Concept Scheme']);
  });

  it('ontology in focus: New Class only (no New Concept, property creation parked)', () => {
    collectionsMock = [ONTOLOGY];
    renderExplore();
    expect(menuLabels()).toEqual(['New Class', 'New Concept Scheme']);
    expect(screen.getByTestId('menu-separator')).toBeInTheDocument();
  });

  it('several editable schemes, none in focus: full set', () => {
    collectionsMock = [GLOSSARY, TAXONOMY, ONTOLOGY];
    renderExplore();
    expect(menuLabels()).toEqual(['New Term', 'New Concept', 'New Class', 'New Concept Scheme']);
  });

  it('no single scheme in focus offers the full set even if no scheme fits a type', () => {
    collectionsMock = [GLOSSARY, TAXONOMY];
    renderExplore();
    expect(menuLabels()).toEqual(['New Term', 'New Concept', 'New Class', 'New Concept Scheme']);
    expect(screen.queryByRole('menuitem', { name: /New Property/ })).not.toBeInTheDocument();
  });

  it('source filter leaving one editable scheme visible focuses it', () => {
    collectionsMock = [GLOSSARY, ONTOLOGY];
    hiddenSourcesMock = ['business'];
    renderExplore();
    expect(menuLabels()).toEqual(['New Class', 'New Concept Scheme']);
  });

  it('source filter compares the scheme source_key when the backend sends one', () => {
    // Demo-style scheme: concepts are grouped under "Demo Data", not the stripped IRI.
    const DEMO = { iri: 'urn:demo', label: 'Demo', collection_type: 'glossary', is_editable: true, source_key: 'Demo Data' };
    collectionsMock = [DEMO, ONTOLOGY];
    hiddenSourcesMock = ['Demo Data'];
    renderExplore();
    expect(menuLabels()).toEqual(['New Class', 'New Concept Scheme']);
  });

  it('picking an item opens the editor preset to that type and the focused scheme', async () => {
    collectionsMock = [ONTOLOGY];
    renderExplore();
    fireEvent.click(screen.getByRole('menuitem', { name: /New Class/ }));
    await waitFor(() => expect(editorProps.open).toBe(true));
    expect(editorProps.initialConceptType).toBe('class');
    expect(editorProps.collection).toEqual(ONTOLOGY);
  });

  it('generic pick targets the first scheme that fits the type', async () => {
    collectionsMock = [GLOSSARY, TAXONOMY, ONTOLOGY];
    renderExplore();
    fireEvent.click(screen.getByRole('menuitem', { name: /New Class/ }));
    await waitFor(() => expect(editorProps.open).toBe(true));
    expect(editorProps.initialConceptType).toBe('class');
    expect(editorProps.collection).toEqual(ONTOLOGY);
  });

  it('generic pick with no fitting scheme leaves the scheme unset', async () => {
    collectionsMock = [GLOSSARY, TAXONOMY];
    renderExplore();
    fireEvent.click(screen.getByRole('menuitem', { name: /New Class/ }));
    await waitFor(() => expect(editorProps.open).toBe(true));
    expect(editorProps.collection).toBeUndefined();
  });

  it('onCreateScheme closes the entry editor and opens the scheme editor preset to the kind', async () => {
    collectionsMock = [GLOSSARY, TAXONOMY];
    renderExplore();
    fireEvent.click(screen.getByRole('menuitem', { name: /New Class/ }));
    await waitFor(() => expect(editorProps.open).toBe(true));
    act(() => editorProps.onCreateScheme('ontology'));
    await waitFor(() => expect(schemeEditorProps.open).toBe(true));
    expect(editorProps.open).toBe(false);
    expect(schemeEditorProps.collection).toBeNull();
    expect(schemeEditorProps.initialCollectionType).toBe('ontology');
  });

  it('the menu New Concept Scheme opens the scheme editor without a preset kind', async () => {
    collectionsMock = [GLOSSARY];
    renderExplore();
    fireEvent.click(screen.getByRole('menuitem', { name: /New Concept Scheme/ }));
    await waitFor(() => expect(schemeEditorProps.open).toBe(true));
    expect(schemeEditorProps.initialCollectionType).toBeUndefined();
  });
});

describe('Explore SPARQL panel', () => {
  it('has no SPARQL toggle in Simple view', () => {
    renderExplore();
    expect(screen.queryByRole('button', { name: /SPARQL/ })).not.toBeInTheDocument();
    expect(screen.queryByTestId('kg-search')).not.toBeInTheDocument();
  });

  it('Advanced view: toggle is adv-only and opens/closes the full-width panel', async () => {
    modeMock = 'advanced';
    renderExplore();
    const toggle = screen.getByRole('button', { name: /SPARQL/ });
    expect(toggle).toHaveClass('adv-only');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByTestId('explore-sparql-panel')).not.toBeInTheDocument();

    fireEvent.click(toggle);
    const panel = await screen.findByTestId('explore-sparql-panel');
    expect(panel).toHaveClass('adv-only');
    expect(panel.className).toContain('min-h-[420px]');
    expect(screen.getByTestId('kg-search')).toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(toggle);
    await waitFor(() => expect(screen.queryByTestId('explore-sparql-panel')).not.toBeInTheDocument());
  });
});

describe('Explore empty state', () => {
  it('no concepts at all: shows the empty block with a link to Define, keeps header and filters', async () => {
    groupedConceptsMock = { 'my-scheme': [] };
    const observe = renderExplore();
    expect(screen.getByTestId('explore-empty-state')).toBeInTheDocument();
    expect(screen.getByText('Nothing to explore yet')).toBeInTheDocument();
    expect(screen.getByText('Import files or create concepts on the Define tab.')).toBeInTheDocument();
    expect(screen.getByTestId('filter-panel')).toBeInTheDocument();
    expect(screen.getByTestId('create-menu')).toBeInTheDocument();
    expect(screen.queryByTestId('concepts-tab')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Go to Define' }));
    await waitFor(() => expect(observe().pathname).toBe('/concepts/define'));
  });

  it('no groups at all also counts as empty', () => {
    groupedConceptsMock = {};
    renderExplore();
    expect(screen.getByTestId('explore-empty-state')).toBeInTheDocument();
  });

  it('filters that hide everything keep ConceptsTab (its own "No concepts found")', () => {
    hiddenSourcesMock = ['my-scheme'];
    renderExplore();
    expect(screen.queryByTestId('explore-empty-state')).not.toBeInTheDocument();
    expect(screen.getByTestId('concepts-tab')).toBeInTheDocument();
  });
});
