import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import type { KnowledgeCollection, OntologyConcept } from '@/types/ontology';

// ---------------------------------------------------------------------------
// ConceptsTab scheme labels.
//
// Group headers (tree and list) and the Scheme column must all use the
// collection record's label, looked up by the key concepts are grouped under
// (source_context == collection source_key). The prettifier mock returns the
// raw key, so a header showing the collection label proves the lookup.
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: any, opts?: Record<string, unknown>) =>
      typeof fallback === 'string'
        ? fallback.replace(/\{\{(\w+)\}\}/g, (m, k) => (opts && k in opts ? String(opts[k]) : m))
        : key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/lib/ontology-utils', () => ({
  resolveLabel: (c: OntologyConcept) => c.label ?? c.iri,
}));

vi.mock('@/lib/system-rdf-namespace-labels', () => ({
  systemRdfNamespaceDisplayLabel: (id: string) => id,
}));

const storeState = {
  expandedConceptGroups: [] as string[],
  toggleConceptGroup: vi.fn(),
  setExpandedConceptGroups: vi.fn(),
  conceptListScrollTop: 0,
  setConceptListScrollTop: vi.fn(),
  conceptListSearch: '',
  setConceptListSearch: vi.fn(),
};
vi.mock('@/stores/glossary-preferences-store', () => ({
  useGlossaryPreferencesStore: (selector: any) => selector(storeState),
}));

import { ConceptsTab } from './concepts-tab';

const concept = (iri: string, label: string, sourceContext: string, sourceFile?: string) =>
  ({
    iri,
    label,
    concept_type: 'concept',
    parent_concepts: [],
    child_concepts: [],
    source_context: sourceContext,
    source_file: sourceFile,
  }) as unknown as OntologyConcept;

const collection = (
  iri: string,
  label: string,
  extra: Partial<KnowledgeCollection> = {},
): KnowledgeCollection =>
  ({ iri, label, child_collections: [], ...extra }) as unknown as KnowledgeCollection;

const baseProps = {
  groupedConcepts: {} as any,
  selectedConcept: null,
  onSelectConcept: vi.fn(),
  groupBySource: true,
  showProperties: false,
  groupByDomain: false,
  selectedLanguage: 'en',
};

const SUPPLY = concept('urn:c:supplier', 'Supplier', 'supply-chain');

beforeEach(() => {
  vi.clearAllMocks();
  storeState.conceptListSearch = '';
  storeState.expandedConceptGroups = [];
});

describe('ConceptsTab scheme labels', () => {
  it('tree group header shows the collection label, not the key', () => {
    render(
      <ConceptsTab
        {...baseProps}
        viewMode="tree"
        collections={[collection('urn:ontology:supply-chain', 'Supply Chain Ontology')]}
        filteredConcepts={[SUPPLY]}
      />,
    );
    expect(screen.getByTestId('concept-group-supply-chain')).toHaveTextContent('Supply Chain Ontology');
  });

  it('list group header shows the collection label, not the key', () => {
    render(
      <ConceptsTab
        {...baseProps}
        viewMode="list"
        collections={[collection('urn:ontology:supply-chain', 'Supply Chain Ontology')]}
        filteredConcepts={[SUPPLY]}
      />,
    );
    // Header label + Scheme column cell.
    expect(screen.getAllByText('Supply Chain Ontology').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('supply-chain')).not.toBeInTheDocument();
  });

  it('a renamed collection updates headers (both views) and the Scheme column', () => {
    const before = [collection('urn:ontology:supply-chain', 'Supply Chain Ontology')];
    const after = [collection('urn:ontology:supply-chain', 'Supply Chain Ontology TEST')];

    const tree = render(
      <ConceptsTab {...baseProps} viewMode="tree" collections={before} filteredConcepts={[SUPPLY]} />,
    );
    expect(screen.getByTestId('concept-group-supply-chain')).toHaveTextContent('Supply Chain Ontology');
    tree.rerender(
      <ConceptsTab {...baseProps} viewMode="tree" collections={after} filteredConcepts={[SUPPLY]} />,
    );
    expect(screen.getByTestId('concept-group-supply-chain')).toHaveTextContent('Supply Chain Ontology TEST');
    tree.unmount();

    const list = render(
      <ConceptsTab {...baseProps} viewMode="list" collections={before} filteredConcepts={[SUPPLY]} />,
    );
    expect(screen.queryByText('Supply Chain Ontology TEST')).not.toBeInTheDocument();
    list.rerender(
      <ConceptsTab {...baseProps} viewMode="list" collections={after} filteredConcepts={[SUPPLY]} />,
    );
    // Header and Scheme column both carry the new label; the old one is gone.
    expect(screen.getAllByText('Supply Chain Ontology TEST').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('Supply Chain Ontology')).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId('concept-row-urn:c:supplier')).getByText('Supply Chain Ontology TEST'),
    ).toBeInTheDocument();
  });

  it('finds a child scheme nested in child_collections', () => {
    const parent = collection('urn:glossary:enterprise', 'Enterprise Glossary', {
      child_collections: [collection('urn:glossary:finance', 'Finance Glossary')],
    });
    render(
      <ConceptsTab
        {...baseProps}
        viewMode="tree"
        collections={[parent]}
        filteredConcepts={[concept('urn:c:ledger', 'Ledger', 'finance')]}
      />,
    );
    expect(screen.getByTestId('concept-group-finance')).toHaveTextContent('Finance Glossary');
  });

  it('maps a collection via source_key (urn:demo grouped as "Demo Data")', () => {
    render(
      <ConceptsTab
        {...baseProps}
        viewMode="tree"
        collections={[collection('urn:demo', 'Demo Scheme', { source_key: 'Demo Data' })]}
        filteredConcepts={[concept('urn:c:order', 'Order', 'Demo Data')]}
      />,
    );
    expect(screen.getByTestId('concept-group-Demo Data')).toHaveTextContent('Demo Scheme');
  });

  it('falls back to the prettifier when no collection record matches', () => {
    render(
      <ConceptsTab
        {...baseProps}
        viewMode="tree"
        collections={[collection('urn:ontology:other', 'Other Ontology')]}
        filteredConcepts={[SUPPLY]}
      />,
    );
    const header = screen.getByTestId('concept-group-supply-chain');
    expect(header).toHaveTextContent('supply-chain');
    expect(header).not.toHaveTextContent('Other Ontology');
  });

  it('group-by-file headers show the file name verbatim', () => {
    const fileConcept = concept('urn:c:sku', 'SKU', 'supply-chain', 'supply_chain_v2.ttl');
    const props = {
      ...baseProps,
      groupBySource: false,
      groupByFile: true,
      collections: [collection('urn:ontology:supply-chain', 'Supply Chain Ontology')],
      filteredConcepts: [fileConcept],
    };
    const tree = render(<ConceptsTab {...props} viewMode="tree" />);
    expect(screen.getByTestId('concept-group-supply_chain_v2.ttl')).toHaveTextContent('supply_chain_v2.ttl');
    tree.unmount();
    render(<ConceptsTab {...props} viewMode="list" />);
    expect(screen.getByText('supply_chain_v2.ttl')).toBeInTheDocument();
  });
});
