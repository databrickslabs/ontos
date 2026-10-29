/**
 * Regression tests for the Manage Lineage wizard:
 * - #686: send the ontology type name ("DataProduct"), not the rdfs:label
 *   ("Data Product"), as `target_type` when searching for link candidates.
 * - #1241: on an incoming step, search for and save the *source* type; the
 *   current entity is the target.
 */
import { screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderWithProviders, userEvent } from '@/test/utils';
import { LineageEditor } from './lineage-editor';

const ONTOS = 'http://ontos.app/ontology#';

const outgoingSchema = {
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

// Shaped like the backend's answer for a DataProduct: on incoming definitions the
// other type is in source_type_*, the current one in target_type_*.
const incomingSchema = {
  type_iri: `${ONTOS}DataProduct`,
  outgoing: [],
  incoming: [
    {
      property_iri: `${ONTOS}containsProduct`,
      property_name: 'containsProduct',
      label: 'Domain',
      inverse_label: 'Contains Products',
      source_type_iri: `${ONTOS}DataDomain`,
      source_type_label: 'Data Domain',
      target_type_iri: `${ONTOS}DataProduct`,
      target_type_label: 'Data Product',
      cardinality: '0..*',
      display_context: 'tab',
      direction: 'incoming',
    },
    {
      property_iri: `${ONTOS}appliesTo`,
      property_name: 'appliesTo',
      label: 'Governed By Policy',
      inverse_label: 'Applies To',
      source_type_iri: `${ONTOS}Policy`,
      source_type_label: 'Policy',
      target_type_iri: `${ONTOS}DataProduct`,
      target_type_label: 'Data Product',
      cardinality: '0..*',
      display_context: 'tab',
      direction: 'incoming',
    },
  ],
};

let schema: typeof outgoingSchema | typeof incomingSchema = outgoingSchema;
let candidate = { id: 'p1', name: 'Sales Product', entity_type: 'DataProduct', score: 1 };

const fetchMock = vi.fn();

function linkCandidateTypes(): (string | null)[] {
  return fetchMock.mock.calls
    .map(c => String(c[0]))
    .filter(u => u.includes('/api/suggestions/link-candidates'))
    .map(u => new URL(u, 'http://localhost').searchParams.get('target_type'));
}

function postedRelationship() {
  const post = fetchMock.mock.calls.find(
    c => String(c[0]) === '/api/entity-relationships' && c[1]?.method === 'POST',
  );
  return post ? JSON.parse(post[1].body) : undefined;
}

beforeEach(() => {
  schema = outgoingSchema;
  candidate = { id: 'p1', name: 'Sales Product', entity_type: 'DataProduct', score: 1 };
  fetchMock.mockReset();
  fetchMock.mockImplementation((url: string) => {
    if (url.includes('/api/ontology/entity-types/relationships')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(schema) });
    }
    if (url.includes('/api/suggestions/link-candidates')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ candidates: [candidate], total: 1 }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('LineageEditor candidate search', () => {
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
      expect(linkCandidateTypes()[0]).toBe('DataProduct');
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
      expect(postedRelationship()).toMatchObject({
        source_type: 'DataContract',
        target_type: 'DataProduct',
        target_id: 'p1',
      });
    });
  });
});

describe('LineageEditor incoming steps (#1241)', () => {
  beforeEach(() => {
    schema = incomingSchema;
    candidate = { id: 'd1', name: 'Sales Domain', entity_type: 'DataDomain', score: 1 };
  });

  const renderEditor = () => renderWithProviders(
    <LineageEditor
      isOpen
      onOpenChange={() => {}}
      entityType="DataProduct"
      entityId="dp1"
      entityName="Orders"
    />,
  );

  it('searches for the source type and shows its icon', async () => {
    renderEditor();

    await waitFor(() => {
      expect(linkCandidateTypes()[0]).toBe('DataDomain');
    });
    expect(linkCandidateTypes()).not.toContain('DataProduct');

    // The policy step shows the Policy icon, not the current type's (Package).
    const policyStep = screen.getByRole('button', { name: /governed by policy/i });
    expect(policyStep.querySelector('svg.lucide-shield')).not.toBeNull();
    expect(policyStep.querySelector('svg.lucide-package')).toBeNull();
  });

  it('reviews the candidate as the source and POSTs it as the source', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(await screen.findByRole('button', { name: /^add$/i }));
    await user.click(screen.getByRole('button', { name: /review & save/i }));

    // "<candidate> [its type] —[rel]→ <this entity's type>", all with display labels.
    const row = (await screen.findByText('Sales Domain')).parentElement!;
    expect(row.textContent).toBe('Sales DomainData Domain—[containsProduct]→Data Product');
    expect(screen.queryByText('DataProduct')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /save all/i }));

    await waitFor(() => {
      expect(postedRelationship()).toEqual({
        source_type: 'DataDomain',
        source_id: 'd1',
        target_type: 'DataProduct',
        target_id: 'dp1',
        relationship_type: 'containsProduct',
      });
    });
  });
});
