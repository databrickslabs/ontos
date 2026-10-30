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
      if (url.startsWith('/api/assets')) {
        return {
          data: {
            items: [{ id: 'p1', name: 'Sales Product', asset_type_name: 'Data Product' }],
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

    // The only matching asset type is auto-selected and its assets are listed.
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
