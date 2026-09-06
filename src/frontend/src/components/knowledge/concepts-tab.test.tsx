import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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
    t: (key: string, fallback?: any) =>
      typeof fallback === 'string' ? fallback : key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/lib/ontology-utils', () => ({
  resolveLabel: (c: OntologyConcept) => c.label ?? c.iri,
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
