import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { OntologyConcept } from '@/types/ontology';

// ---------------------------------------------------------------------------
// ConceptsTab view-mode tests.
//
// Asserts the additive list/tree distinction:
//  - tree mode nests broader/narrower concepts (child indented under parent),
//  - list mode renders a FLAT, alphabetically-sorted list (no nesting, no
//    parent/child indentation) over the same concept row markup.
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
  resolveLabel: (c: OntologyConcept, lang?: string) =>
    (c as any).labels?.[lang ?? 'en'] ?? c.label ?? c.iri,
}));

vi.mock('@/lib/system-rdf-namespace-labels', () => ({
  systemRdfNamespaceDisplayLabel: (id: string) => id,
}));

// Store: expose a simple in-memory state via the selector signature the
// component uses (useStore((s) => s.field)).
const storeState = {
  expandedConceptGroups: ['urn:parent'],
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

// Parent -> Child hierarchy. In tree mode Child nests under Parent; in list
// mode both are flat siblings.
const PARENT = {
  iri: 'urn:parent',
  label: 'Parent',
  concept_type: 'concept',
  parent_concepts: [],
  child_concepts: ['urn:child'],
} as unknown as OntologyConcept;

const CHILD = {
  iri: 'urn:child',
  label: 'Child',
  concept_type: 'concept',
  parent_concepts: ['urn:parent'],
  child_concepts: [],
} as unknown as OntologyConcept;

const CONCEPTS = [PARENT, CHILD];

const baseProps = {
  collections: [],
  groupedConcepts: {} as any,
  filteredConcepts: CONCEPTS,
  selectedConcept: null,
  onSelectConcept: vi.fn(),
  groupBySource: false,
  showProperties: false,
  groupByDomain: false,
  selectedLanguage: 'en',
};

beforeEach(() => {
  vi.clearAllMocks();
  storeState.conceptListSearch = '';
  storeState.expandedConceptGroups = ['urn:parent'];
});

describe('ConceptsTab view modes', () => {
  it('tree mode nests the child under the parent (indented)', () => {
    render(<ConceptsTab {...baseProps} viewMode="tree" />);
    const parent = screen.getByTestId('concept-row-urn:parent');
    const child = screen.getByTestId('concept-row-urn:child');
    // Child is rendered inside the parent's subtree wrapper -> the parent row
    // is NOT an ancestor of the child, but the child sits deeper in the DOM
    // (inside an ml-2 wrapper). Assert nesting via padding-left indentation.
    const childPad = parseInt(child.style.paddingLeft || '0', 10);
    const parentPad = parseInt(parent.style.paddingLeft || '0', 10);
    expect(childPad).toBeGreaterThan(parentPad);
  });

  it('list mode renders a flat list with no parent/child indentation', () => {
    render(<ConceptsTab {...baseProps} viewMode="list" />);
    const parent = screen.getByTestId('concept-row-urn:parent');
    const child = screen.getByTestId('concept-row-urn:child');
    // Both rows share the same (root-level) indentation in flat mode.
    expect(parent.style.paddingLeft).toBe(child.style.paddingLeft);
  });

  it('list mode has no expand/collapse controls (no chevrons)', () => {
    render(<ConceptsTab {...baseProps} viewMode="list" />);
    // Tree mode renders expand buttons for folder rows; flat mode never does.
    expect(screen.queryByLabelText('Expand')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Collapse')).not.toBeInTheDocument();
  });

  it('defaults to tree mode when viewMode is omitted', () => {
    render(<ConceptsTab {...baseProps} />);
    const parent = screen.getByTestId('concept-row-urn:parent');
    const child = screen.getByTestId('concept-row-urn:child');
    const childPad = parseInt(child.style.paddingLeft || '0', 10);
    const parentPad = parseInt(parent.style.paddingLeft || '0', 10);
    expect(childPad).toBeGreaterThan(parentPad);
  });

  it('list mode sorts concepts alphabetically by label', () => {
    render(<ConceptsTab {...baseProps} viewMode="list" />);
    const rows = screen.getAllByTestId(/^concept-row-/);
    const labels = rows.map((r) => r.textContent?.match(/Child|Parent/)?.[0]);
    // Child sorts before Parent.
    expect(labels[0]).toBe('Child');
    expect(labels[1]).toBe('Parent');
  });
});

describe('ConceptsTab search (list view)', () => {
  const CUSTOMER = {
    iri: 'urn:customer',
    label: 'Customer',
    labels: { en: 'Customer', nl: 'Klant' },
    concept_type: 'concept',
    parent_concepts: [],
    child_concepts: [],
  } as unknown as OntologyConcept;
  const CUSTOMS = {
    iri: 'urn:customs',
    label: 'Customs duty',
    concept_type: 'concept',
    parent_concepts: [],
    child_concepts: [],
  } as unknown as OntologyConcept;
  const ACCOUNT = {
    iri: 'urn:account',
    label: 'Account customer',
    concept_type: 'concept',
    parent_concepts: [],
    child_concepts: [],
  } as unknown as OntologyConcept;
  const props = { ...baseProps, filteredConcepts: [ACCOUNT, CUSTOMS, CUSTOMER] };

  it('filters the list by the search query', () => {
    storeState.conceptListSearch = 'parent';
    render(<ConceptsTab {...baseProps} viewMode="list" />);
    expect(screen.getByTestId('concept-row-urn:parent')).toBeInTheDocument();
    expect(screen.queryByTestId('concept-row-urn:child')).not.toBeInTheDocument();
  });

  it('matches another-language label and shows a "matched: nl" hint', () => {
    storeState.conceptListSearch = 'klant';
    render(<ConceptsTab {...props} viewMode="list" />);
    expect(screen.getByTestId('concept-row-urn:customer')).toBeInTheDocument();
    expect(screen.queryByTestId('concept-row-urn:customs')).not.toBeInTheDocument();
    expect(screen.getByTestId('concept-match-lang-urn:customer')).toHaveTextContent('matched: nl');
  });

  it('sorts prefix matches before substring matches', () => {
    storeState.conceptListSearch = 'custom';
    render(<ConceptsTab {...props} viewMode="list" />);
    const rows = screen.getAllByTestId(/^concept-row-/).map((r) => r.getAttribute('data-testid'));
    // Customer + Customs duty are prefix hits (alphabetical), Account customer is a substring hit.
    expect(rows).toEqual(['concept-row-urn:customer', 'concept-row-urn:customs', 'concept-row-urn:account']);
    expect(screen.queryByTestId(/^concept-match-lang-/)).not.toBeInTheDocument();
  });

  it('tree view uses the same matcher (other-language label hit)', () => {
    storeState.conceptListSearch = 'klant';
    render(<ConceptsTab {...props} viewMode="tree" />);
    expect(screen.getByTestId('concept-row-urn:customer')).toBeInTheDocument();
    expect(screen.queryByTestId('concept-row-urn:account')).not.toBeInTheDocument();
  });
});

describe('ConceptsTab bulk lifecycle actions', () => {
  it('grays out transitions that do not apply to the selected status', async () => {
    const user = userEvent.setup();
    const published = { ...PARENT, status: 'published' } as unknown as OntologyConcept;
    render(<ConceptsTab {...baseProps} filteredConcepts={[published]} viewMode="list" />);

    fireEvent.click(screen.getByRole('checkbox', { name: 'Select' }));
    await user.click(screen.getByRole('button', { name: /Set status/ }));

    expect(screen.getByTestId('bulk-status-certify')).not.toHaveAttribute('data-disabled');
    expect(screen.getByTestId('bulk-status-publish')).toHaveAttribute('data-disabled');
    expect(screen.getByTestId('bulk-status-approve')).toHaveAttribute('data-disabled');
  });
});

describe('ConceptsTab tree ordering', () => {
  const mk = (iri: string, label: string, parents: string[] = [], labels?: any) =>
    ({
      iri,
      label,
      labels,
      concept_type: 'concept',
      parent_concepts: parents,
      child_concepts: [],
    }) as unknown as OntologyConcept;

  const order = () =>
    screen
      .getAllByTestId(/^concept-row-/)
      .map((r) => r.getAttribute('data-testid')!.replace('concept-row-', ''));

  it('sorts roots and children alphabetically, not in API order', () => {
    const concepts = [
      mk('urn:r-zeta', 'Zeta'),
      mk('urn:r-alpha', 'alpha'),
      mk('urn:c-two', 'Banana', ['urn:r-alpha']),
      mk('urn:c-one', 'Apple', ['urn:r-alpha']),
    ];
    storeState.expandedConceptGroups = ['urn:r-alpha'];
    render(<ConceptsTab {...baseProps} filteredConcepts={concepts} viewMode="tree" />);
    expect(order()).toEqual(['urn:r-alpha', 'urn:c-one', 'urn:c-two', 'urn:r-zeta']);
  });

  it('sorts by the label in the selected language and breaks ties by IRI', () => {
    const concepts = [
      mk('urn:b', 'Apple', [], { pt: 'Zebra' }),
      mk('urn:a', 'Zulu', [], { pt: 'Abelha' }),
      mk('urn:d', 'Same', [], { pt: 'Igual' }),
      mk('urn:c', 'Same', [], { pt: 'Igual' }),
    ];
    storeState.expandedConceptGroups = [];
    render(
      <ConceptsTab
        {...baseProps}
        filteredConcepts={concepts}
        selectedLanguage="pt"
        viewMode="tree"
      />,
    );
    expect(order()).toEqual(['urn:a', 'urn:c', 'urn:d', 'urn:b']);
  });

  it('group-by-domain keeps child concepts before domain properties, each sorted', () => {
    const prop = (iri: string, label: string) =>
      ({ ...mk(iri, label), concept_type: 'property', domain: 'urn:root' }) as OntologyConcept;
    const concepts = [
      mk('urn:root', 'Root'),
      prop('urn:p-b', 'Beta prop'),
      prop('urn:p-a', 'Alpha prop'),
      mk('urn:c-z', 'Zed child', ['urn:root']),
      mk('urn:c-m', 'Mid child', ['urn:root']),
      // A property that is also a hierarchy child must appear once.
      { ...prop('urn:p-c', 'Gamma prop'), parent_concepts: ['urn:root'] } as OntologyConcept,
    ];
    storeState.expandedConceptGroups = ['urn:root'];
    render(
      <ConceptsTab
        {...baseProps}
        filteredConcepts={concepts}
        groupByDomain
        showProperties
        viewMode="tree"
      />,
    );
    expect(order()).toEqual(['urn:root', 'urn:p-c', 'urn:c-m', 'urn:c-z', 'urn:p-a', 'urn:p-b']);
  });

  it('group-by-source sorts the concepts inside each group', () => {
    const inCtx = (iri: string, label: string) =>
      ({ ...mk(iri, label), source_context: 'scheme-a' }) as OntologyConcept;
    const concepts = [inCtx('urn:z', 'Zeta'), inCtx('urn:a', 'Alpha'), inCtx('urn:m', 'Mid')];
    storeState.expandedConceptGroups = ['scheme-a'];
    render(
      <ConceptsTab {...baseProps} filteredConcepts={concepts} groupBySource viewMode="tree" />,
    );
    expect(order().filter((id) => id.startsWith('urn:'))).toEqual(['urn:a', 'urn:m', 'urn:z']);
  });
});
