/**
 * Regression test for #686: the Manage Lineage wizard must send the ontology
 * type name ("DataProduct"), not the rdfs:label ("Data Product"), as
 * `target_type` when searching for link candidates.
 */
import { screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderWithProviders, userEvent } from '@/test/utils';
import { LineageEditor } from './lineage-editor';

const relationships = {
  type_iri: 'http://ontos.app/ontology#DataContract',
  outgoing: [
    {
      property_iri: 'http://ontos.app/ontology#hasProduct',
      property_name: 'hasProduct',
      label: 'has product',
      source_type_iri: 'http://ontos.app/ontology#DataContract',
      source_type_label: 'Data Contract',
      target_type_iri: 'http://ontos.app/ontology#DataProduct',
      target_type_label: 'Data Product',
      cardinality: '0..*',
      display_context: 'tab',
      direction: 'outgoing',
    },
  ],
  incoming: [],
};

describe('LineageEditor candidate search', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockImplementation((url: string) => {
      if (url.includes('/api/ontology/entity-types/relationships')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(relationships) });
      }
      if (url.includes('/api/suggestions/link-candidates')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            candidates: [{ id: 'p1', name: 'Sales Product', entity_type: 'DataProduct', score: 1 }],
            total: 1,
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('requests link-candidates with the machine type name, not the display label', async () => {
    renderWithProviders(
      <LineageEditor
        isOpen
        onOpenChange={() => {}}
        entityType="DataContract"
        entityId="c1"
        entityName="Contract"
      />,
    );

    await waitFor(() => {
      const urls = fetchMock.mock.calls
        .map(c => String(c[0]))
        .filter(u => u.includes('/api/suggestions/link-candidates'));
      expect(urls.length).toBeGreaterThan(0);
      const params = new URL(urls[0], 'http://localhost').searchParams;
      expect(params.get('target_type')).toBe('DataProduct');
    });
    // Display text still uses the human-readable label.
    expect(screen.getAllByText(/has product/i).length).toBeGreaterThan(0);
  });

  it('shows the display label in the review step but POSTs the machine type name', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <LineageEditor
        isOpen
        onOpenChange={() => {}}
        entityType="DataContract"
        entityId="c1"
        entityName="Contract"
      />,
    );

    await user.click(await screen.findByRole('button', { name: /^add$/i }));
    await user.click(screen.getByRole('button', { name: /review & save/i }));

    expect(await screen.findByText('Data Product')).toBeInTheDocument();
    expect(screen.queryByText('DataProduct')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /save all/i }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        c => String(c[0]) === '/api/entity-relationships' && c[1]?.method === 'POST',
      );
      expect(post).toBeDefined();
      expect(JSON.parse(post![1].body)).toMatchObject({
        source_type: 'DataContract',
        target_type: 'DataProduct',
        target_id: 'p1',
      });
    });
  });
});
