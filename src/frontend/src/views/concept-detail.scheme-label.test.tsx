/**
 * The concept detail page shows the scheme record's current label (summary
 * and Details panels), found by exact source key across nested child schemes,
 * so a renamed scheme shows its new name. Without a matching record it falls
 * back to the prettified source key.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const get = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get, post: vi.fn(), put: vi.fn(), delete: vi.fn() }),
}));
vi.mock('@/stores/permissions-store', async (orig) => {
  const actual = await orig<Record<string, unknown>>();
  return { ...actual, usePermissions: () => ({ hasPermission: () => true }) };
});

// Heavy child panels fetch their own data; they are irrelevant here.
const { Stub } = vi.hoisted(() => ({ Stub: () => null }));
vi.mock('@/components/semantic/concept-relations-panel', () => ({ default: Stub }));
vi.mock('@/components/semantic/linked-objects-panel', () => ({ default: Stub }));
vi.mock('@/components/semantic/concept-neighborhood-graph', () => ({ default: Stub }));
vi.mock('@/components/knowledge/concept-editor-dialog', () => ({ ConceptEditorDialog: Stub }));
vi.mock('@/components/common/ownership-panel', () => ({ OwnershipPanel: Stub }));
vi.mock('@/components/metadata/entity-metadata-panel', () => ({ default: Stub }));
vi.mock('@/components/semantic/publish-version-dialog', () => ({ PublishVersionDialog: Stub }));
vi.mock('@/components/semantic/version-history-panel', () => ({ VersionHistoryPanel: Stub }));
vi.mock('@/components/semantic/deprecate-concept-dialog', () => ({ DeprecateConceptDialog: Stub }));
vi.mock('@/components/semantic/turtle-serialization-panel', () => ({ TurtleSerializationPanel: Stub }));
vi.mock('@/components/workflows/approval-wizard-dialog', () => ({ default: Stub }));
vi.mock('@/components/concepts/request-concept-action-dialog', () => ({ RequestConceptActionDialog: Stub }));
vi.mock('@/components/comments', () => ({ CommentSidebar: Stub }));
vi.mock('@/components/semantic/status-progress-bar', () => ({ StatusProgressBar: Stub }));

import ConceptDetailView from './concept-detail';

const IRI = 'http://example.org/concepts/Shipment';
const LABEL = 'Supply Chain Ontology TEST';

let collections: unknown[] = [];

function scheme(label: string, extra: Record<string, unknown> = {}) {
  return { iri: 'urn:ontology:supply-chain', source_key: 'supply-chain', label, is_editable: true, ...extra };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/concepts/${encodeURIComponent(IRI)}`]}>
      <Routes>
        <Route path="/concepts/*" element={<ConceptDetailView />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function schemeTexts() {
  const summary = await screen.findByTestId('concept-summary-panel');
  const details = screen.getByTestId('concept-panels').querySelector<HTMLElement>('[data-panel="details"]')!;
  return { summary: within(summary), details: within(details) };
}

describe('ConceptDetailView scheme label', () => {
  beforeEach(() => {
    collections = [scheme(LABEL)];
    get.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/semantic-models/concepts/by-iri')) {
        return {
          data: {
            concept: {
              iri: IRI,
              label: 'Shipment',
              concept_type: 'concept',
              status: 'draft',
              source_context: 'supply-chain',
              labels: {},
              comments: {},
              parent_concepts: [],
              child_concepts: [],
            },
          },
        };
      }
      if (url.startsWith('/api/knowledge/collections')) return { data: { collections } };
      return { data: {} };
    });
  });

  it('shows the scheme label in the summary and Details panels', async () => {
    renderPage();
    const { summary, details } = await schemeTexts();
    expect(await summary.findByText(LABEL)).toBeInTheDocument();
    expect(details.getAllByText(LABEL).length).toBeGreaterThan(0);
    expect(screen.queryByText('Supply Chain')).toBeNull();
  });

  it('shows the new label after a rename', async () => {
    collections = [scheme('Old Scheme Name')];
    const first = renderPage();
    expect(await (await schemeTexts()).summary.findByText('Old Scheme Name')).toBeInTheDocument();
    first.unmount();

    collections = [scheme(LABEL)];
    renderPage();
    const { summary, details } = await schemeTexts();
    expect(await summary.findByText(LABEL)).toBeInTheDocument();
    expect(details.getAllByText(LABEL).length).toBeGreaterThan(0);
    expect(screen.queryByText('Old Scheme Name')).toBeNull();
  });

  it('finds a nested child scheme', async () => {
    collections = [
      {
        iri: 'urn:ontology:operations',
        source_key: 'operations',
        label: 'Operations',
        is_editable: true,
        child_collections: [scheme(LABEL)],
      },
    ];
    renderPage();
    const { summary, details } = await schemeTexts();
    expect(await summary.findByText(LABEL)).toBeInTheDocument();
    expect(details.getAllByText(LABEL).length).toBeGreaterThan(0);
  });

  it('falls back to the prettified source key without a scheme record', async () => {
    collections = [];
    renderPage();
    const { summary, details } = await schemeTexts();
    expect(await summary.findByText('Supply Chain')).toBeInTheDocument();
    expect(details.getByText('Supply Chain')).toBeInTheDocument();
    expect(screen.queryByText(LABEL)).toBeNull();
  });

  it('resolves the scheme when the concept API sends the full context IRI', async () => {
    // The by-iri concept endpoint returns source_context as the context IRI, not
    // the short group key that concepts-grouped uses.
    get.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/semantic-models/concepts/by-iri')) {
        return {
          data: {
            concept: {
              iri: IRI,
              label: 'Shipment',
              concept_type: 'concept',
              status: 'draft',
              source_context: 'urn:ontology:supply-chain',
              labels: {},
              comments: {},
              parent_concepts: [],
              child_concepts: [],
            },
          },
        };
      }
      if (url.startsWith('/api/knowledge/collections')) return { data: { collections } };
      return { data: {} };
    });
    renderPage();
    const { summary, details } = await schemeTexts();
    expect(await summary.findByText(LABEL)).toBeInTheDocument();
    expect(details.getAllByText(LABEL).length).toBeGreaterThan(0);
  });

  it('shows the scheme once in Details when a record exists', async () => {
    renderPage();
    const { details } = await schemeTexts();
    expect(await details.findAllByText(LABEL)).toHaveLength(1);
  });
});
