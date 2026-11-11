/**
 * Regression test for #686: the Add Relationship dialog must POST the ontology
 * type name ("DataProduct"), not the rdfs:label ("Data Product"), as `target_type`.
 */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: getMock, post: postMock }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
// A native <select> instead of the Radix one: opening a Radix Select inside the Radix
// Dialog makes their focus scopes bounce focus between each other forever in jsdom.
vi.mock('@/components/ui/select', () => ({
  Select: ({ value, onValueChange, children }: any) => (
    <select
      aria-label="relationship type"
      value={value}
      onChange={e => onValueChange(e.target.value)}
    >
      <option value="" />
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ value, children }: any) => <option value={value}>{children}</option>,
}));

import { AddRelationshipDialog } from './add-relationship-dialog';

const ONTOS = 'http://ontos.app/ontology#';

const relationships = {
  type_iri: `${ONTOS}DataContract`,
  outgoing: [
    {
      property_iri: `${ONTOS}hasProduct`,
      property_name: 'hasProduct',
      label: 'has product',
      source_type_iri: `${ONTOS}DataContract`,
      source_type_label: 'Data Contract',
      target_type_iri: `${ONTOS}DataProduct`,
      target_type_label: 'Data Product',
      cardinality: '0..*',
      display_context: 'tab',
      direction: 'outgoing',
    },
  ],
  incoming: [],
};

describe('AddRelationshipDialog create', () => {
  beforeEach(() => {
    getMock.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/ontology/entity-types/relationships')) {
        return { data: relationships };
      }
      if (url.startsWith('/api/asset-types')) {
        return {
          data: [{
            id: 't1', name: 'Data Product', category: 'data', status: 'active', asset_count: 1,
          }],
        };
      }
      if (url.startsWith('/api/suggestions/link-candidates')) {
        return {
          data: {
            candidates: [{ id: 'p1', name: 'Sales Product', entity_type: 'DataProduct' }],
            total: 1,
          },
        };
      }
      return { data: null };
    });
    postMock.mockResolvedValue({ data: { id: 'r1' } });
  });

  it('POSTs the machine type name as target_type, not the display label', async () => {
    renderWithProviders(
      <AddRelationshipDialog
        isOpen
        onOpenChange={() => {}}
        entityType="DataContract"
        entityId="c1"
        onRelationshipCreated={() => {}}
      />,
    );

    const relType = await screen.findByRole('option', { name: /has product/i });
    fireEvent.change(screen.getByRole('combobox', { name: 'relationship type' }), {
      target: { value: (relType as HTMLOptionElement).value },
    });

    // Products aren't assets: they are listed from the link candidates.
    fireEvent.click(await screen.findByText('Sales Product'));
    fireEvent.click(screen.getByRole('button', { name: /create relationship/i }));

    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith('/api/entity-relationships', {
        source_type: 'DataContract',
        source_id: 'c1',
        target_type: 'DataProduct',
        target_id: 'p1',
        relationship_type: 'hasProduct',
      });
    });
  });
});

const rel = (name: string, label: string, target: string, targetLabel: string, sourceLabel = 'Logical Entity') => ({
  property_iri: `${ONTOS}${name}`, property_name: name, label,
  source_type_iri: `${ONTOS}LogicalEntity`, source_type_label: sourceLabel,
  target_type_iri: `${ONTOS}${target}`, target_type_label: targetLabel,
  cardinality: '0..*', display_context: 'tab', direction: 'outgoing',
});

const LOGICAL_ENTITY_RELS = {
  type_iri: `${ONTOS}LogicalEntity`,
  outgoing: [
    rel('belongsToDomain', 'belongs to domain', 'DataDomain', 'Data Domain'),
    rel('hasSemanticConcept', 'has concepts', 'OntologyConcept', 'Ontology Concept'),
    // Translated labels: the asset type must still be found by its local name.
    rel('hasLogicalAttribute', 'has logical attribute', 'LogicalAttribute', 'Logisches Attribut', 'Logische Entität'),
    rel('hasOwner', 'has owner', 'Ownership', 'Ownership'),
  ],
  incoming: [],
};

const DOMAINS = [
  { id: 'd1', name: 'Finance', entity_type: 'DataDomain' },
  { id: 'd2', name: 'Sales', entity_type: 'DataDomain' },
];
const CONCEPTS = [
  { id: 'urn:glossary:retail/customer', name: 'Customer', entity_type: 'OntologyConcept', context: 'Retail Glossary' },
];

describe('AddRelationshipDialog target sources (#956, #957, #959)', () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    getMock.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/ontology/entity-types/relationships')) return { data: LOGICAL_ENTITY_RELS };
      if (url.startsWith('/api/asset-types')) {
        return { data: [{ id: 'la', name: 'Logical Attribute', category: 'data', status: 'active', asset_count: 1 }] };
      }
      if (url.startsWith('/api/assets')) {
        return { data: { items: [{ id: 'a1', name: 'customer_id', asset_type_name: 'Logical Attribute' }], total: 1 } };
      }
      if (url.startsWith('/api/suggestions/link-candidates')) {
        const params = new URLSearchParams(url.split('?')[1]);
        const pool = params.get('target_type') === 'OntologyConcept' ? CONCEPTS : DOMAINS;
        const q = (params.get('query') || '').toLowerCase();
        const candidates = pool.filter(c => c.name.toLowerCase().includes(q));
        return { data: { candidates, total: candidates.length } };
      }
      return { data: null };
    });
    postMock.mockResolvedValue({ data: { id: 'r1' } });
  });

  const open = async (relLabel: RegExp) => {
    renderWithProviders(
      <AddRelationshipDialog
        isOpen
        onOpenChange={() => {}}
        entityType="LogicalEntity"
        entityId="le1"
        onRelationshipCreated={() => {}}
      />,
    );
    const option = await screen.findByRole('option', { name: relLabel });
    fireEvent.change(screen.getByRole('combobox', { name: 'relationship type' }), {
      target: { value: (option as HTMLOptionElement).value },
    });
  };

  const urls = () => getMock.mock.calls.map(([url]) => url as string);
  const candidateCalls = () => urls().filter(url => url.startsWith('/api/suggestions/link-candidates'));

  it('browses domains from the link candidates and creates the link', async () => {
    await open(/belongs to domain/i);

    fireEvent.click(await screen.findByText('Sales'));
    fireEvent.click(screen.getByRole('button', { name: /create relationship/i }));

    expect(candidateCalls()[0]).toContain('target_type=DataDomain');
    expect(urls().some(url => url.startsWith('/api/assets'))).toBe(false);
    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith('/api/entity-relationships', {
        source_type: 'LogicalEntity', source_id: 'le1',
        target_type: 'DataDomain', target_id: 'd2',
        relationship_type: 'belongsToDomain',
      });
    });
  });

  it('filters domains by name in browse mode', async () => {
    await open(/belongs to domain/i);
    await screen.findByText('Finance');

    fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: 'fin' } });

    await waitFor(() => expect(candidateCalls().some(url => url.includes('query=fin'))).toBe(true));
    await waitFor(() => expect(screen.queryByText('Sales')).toBeNull());
    expect(screen.getByText('Finance')).toBeInTheDocument();
  });

  it('searches domains in search mode', async () => {
    await open(/belongs to domain/i);
    await screen.findByText('Finance');
    const searchTab = screen.getByRole('tab', { name: /search/i });
    fireEvent.mouseDown(searchTab);
    fireEvent.click(searchTab);

    fireEvent.change(await screen.findByPlaceholderText(/by name/i), { target: { value: 'sal' } });

    await waitFor(() => expect(candidateCalls().some(url => url.includes('query=sal'))).toBe(true));
    expect(await screen.findByText('Sales')).toBeInTheDocument();
  });

  it('lists concepts with their collection and explains the two kinds of concept links', async () => {
    await open(/has concepts/i);

    fireEvent.click(await screen.findByText('Customer'));
    expect(screen.getByText(/Retail Glossary/)).toBeInTheDocument();
    expect(screen.getByText(/Linked Business Concepts/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /create relationship/i }));

    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith('/api/entity-relationships', {
        source_type: 'LogicalEntity', source_id: 'le1',
        target_type: 'OntologyConcept', target_id: 'urn:glossary:retail/customer',
        relationship_type: 'hasSemanticConcept',
        properties: { target_label: 'Customer' },
      });
    });
  });

  it('finds the asset type by its local name when the label is translated', async () => {
    await open(/has logical attribute/i);

    fireEvent.click(await screen.findByText('customer_id'));

    expect(urls().some(url => url.startsWith('/api/assets?asset_type_id=la'))).toBe(true);
  });

  it('links an "Asset" range with the picked asset\'s own type', async () => {
    getMock.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/ontology/entity-types/relationships')) {
        return { data: { ...LOGICAL_ENTITY_RELS, outgoing: [rel('consumesFrom', 'consumes from', 'Asset', 'Asset')] } };
      }
      if (url.startsWith('/api/asset-types')) {
        return { data: [{ id: 'mv', name: 'Metric View', category: 'data', status: 'active', asset_count: 1 }] };
      }
      if (url.startsWith('/api/assets')) {
        return { data: { items: [{ id: 'v1', name: 'revenue_metrics', asset_type_name: 'Metric View' }], total: 1 } };
      }
      return { data: null };
    });
    await open(/consumes from/i);

    fireEvent.click(await screen.findByText('revenue_metrics'));
    fireEvent.click(screen.getByRole('button', { name: /create relationship/i }));

    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith('/api/entity-relationships', expect.objectContaining({
        target_type: 'MetricView', target_id: 'v1', relationship_type: 'consumesFrom',
      }));
    });
  });

  it('drops an answer that arrives after the relationship type changed', async () => {
    let releaseDomains: (v: unknown) => void = () => {};
    getMock.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/ontology/entity-types/relationships')) return { data: LOGICAL_ENTITY_RELS };
      if (url.startsWith('/api/asset-types')) return { data: [] };
      if (url.startsWith('/api/suggestions/link-candidates')) {
        if (url.includes('target_type=DataDomain')) {
          await new Promise(resolve => { releaseDomains = resolve; });
          return { data: { candidates: DOMAINS, total: 2 } };
        }
        return { data: { candidates: CONCEPTS, total: 1 } };
      }
      return { data: null };
    });
    await open(/belongs to domain/i);
    const option = await screen.findByRole('option', { name: /has concepts/i });
    fireEvent.change(screen.getByRole('combobox', { name: 'relationship type' }), {
      target: { value: (option as HTMLOptionElement).value },
    });
    await screen.findByText('Customer');

    releaseDomains(undefined);

    await new Promise(resolve => setTimeout(resolve, 50));
    expect(screen.queryByText('Sales')).toBeNull();
    expect(screen.getByText('Customer')).toBeInTheDocument();
  });

  it('falls back to an asset search when the asset types fail to load', async () => {
    getMock.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/ontology/entity-types/relationships')) return { data: LOGICAL_ENTITY_RELS };
      if (url.startsWith('/api/asset-types')) return { error: 'boom' };
      return { data: { items: [], total: 0 } };
    });
    await open(/has owner/i);

    await waitFor(() => expect(screen.queryByText(/can't be picked here/i)).toBeNull());
  });

  it('says when a target type is managed elsewhere', async () => {
    await open(/has owner/i);

    expect(await screen.findByText(/can't be picked here/i)).toBeInTheDocument();
    expect(candidateCalls()).toEqual([]);
  });
});
