/**
 * The summary panel shows the scheme label the page resolved from the scheme
 * record, and falls back to the prettified source key when none is passed.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: () => {} }) }));
vi.mock('@/components/semantic/status-progress-bar', () => ({ StatusProgressBar: () => null }));

import { ConceptSummaryPanel } from './concept-summary-panel';
import type { OntologyConcept } from '@/types/ontology';

const concept = {
  iri: 'http://example.org/concepts/Shipment',
  label: 'Shipment',
  concept_type: 'concept',
  status: 'draft',
  source_context: 'supply-chain',
  parent_concepts: [],
  child_concepts: [],
} as unknown as OntologyConcept;

describe('ConceptSummaryPanel scheme label', () => {
  it('renders the schemeLabel prop when given', () => {
    render(<ConceptSummaryPanel concept={concept} title="Shipment" schemeLabel="Supply Chain Ontology TEST" />);
    expect(screen.getByText('Supply Chain Ontology TEST')).toBeInTheDocument();
    expect(screen.queryByText('Supply Chain')).toBeNull();
  });

  it('falls back to the prettified source key when the prop is omitted', () => {
    render(<ConceptSummaryPanel concept={concept} title="Shipment" />);
    expect(screen.getByText('Supply Chain')).toBeInTheDocument();
  });
});
