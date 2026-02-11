/**
 * Focused tests for the "Explore in Graph Explorer" button added in Phase 2b.
 * Tests that:
 * 1. The button renders when a concept is selected
 * 2. Clicking it navigates to /graph-explorer?filterType={label}
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { OntologyConcept, KnowledgeCollection, GroupedConcepts } from '@/types/ontology';

// Mock react-router-dom's useNavigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

// Mock the ontology-utils
vi.mock('@/lib/ontology-utils', () => ({
  resolveLabel: (concept: OntologyConcept) => concept.label || concept.iri,
  resolveComment: (concept: OntologyConcept) => concept.comment,
  getAvailableLanguages: () => ['en'],
  getLanguageDisplayName: (lang: string) => lang,
}));

// Mock NodeLinksPanel since it's a child component
vi.mock('@/components/knowledge/node-links-panel', () => ({
  NodeLinksPanel: () => null,
}));

// Mock EntityMetadataPanel
vi.mock('@/components/metadata/entity-metadata-panel', () => ({
  default: () => null,
}));

import { ConceptsTab } from './concepts-tab';

const makeConcept = (overrides?: Partial<OntologyConcept>): OntologyConcept => ({
  iri: 'urn:test:Customer',
  label: 'Customer',
  comment: 'A customer entity',
  concept_type: 'class',
  parent_concepts: [],
  child_concepts: [],
  properties: [],
  tagged_assets: [],
  synonyms: [],
  examples: [],
  ...overrides,
});

const defaultProps = {
  collections: [] as KnowledgeCollection[],
  groupedConcepts: {} as GroupedConcepts,
  filteredConcepts: [makeConcept()],
  selectedConcept: makeConcept(),
  onSelectConcept: vi.fn(),
  onCreateConcept: vi.fn(),
  onEditConcept: vi.fn(),
  onDeleteConcept: vi.fn(),
  onRefresh: vi.fn().mockResolvedValue(undefined),
  canEdit: false,
  availableSources: [],
  hiddenSources: [],
  groupBySource: false,
  showProperties: false,
  groupByDomain: false,
  isFilterExpanded: false,
  onToggleSource: vi.fn(),
  onSelectAllSources: vi.fn(),
  onSelectNoneSources: vi.fn(),
  onSetGroupBySource: vi.fn(),
  onSetShowProperties: vi.fn(),
  onSetGroupByDomain: vi.fn(),
  onSetFilterExpanded: vi.fn(),
};

describe('ConceptsTab - Explore in Graph Explorer button', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the "Explore in Graph" button when a concept is selected', () => {
    render(
      <MemoryRouter>
        <ConceptsTab {...defaultProps} />
      </MemoryRouter>,
    );

    const btn = screen.getByTestId('explore-in-graph-button');
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent('semantic-models:actions.exploreInGraph');
  });

  it('navigates to /graph-explorer?filterType=<label> on click', () => {
    render(
      <MemoryRouter>
        <ConceptsTab {...defaultProps} />
      </MemoryRouter>,
    );

    const btn = screen.getByTestId('explore-in-graph-button');
    fireEvent.click(btn);

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith('/graph-explorer?filterType=Customer');
  });

  it('does not render the button when no concept is selected', () => {
    render(
      <MemoryRouter>
        <ConceptsTab {...defaultProps} selectedConcept={null} />
      </MemoryRouter>,
    );

    expect(screen.queryByTestId('explore-in-graph-button')).not.toBeInTheDocument();
  });

  it('encodes special characters in the filterType param', () => {
    const specialConcept = makeConcept({ label: 'Data Product & Service' });
    render(
      <MemoryRouter>
        <ConceptsTab
          {...defaultProps}
          selectedConcept={specialConcept}
          filteredConcepts={[specialConcept]}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId('explore-in-graph-button'));

    expect(mockNavigate).toHaveBeenCalledWith(
      '/graph-explorer?filterType=Data%20Product%20%26%20Service',
    );
  });
});
