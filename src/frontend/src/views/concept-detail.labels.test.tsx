/**
 * Concept title and hierarchy badges follow the label precedence (#1616):
 * skos:prefLabel in any language beats rdfs:label in the UI language.
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
vi.mock('@/components/semantic/turtle-serialization-panel', () => ({
  TurtleSerializationPanel: Stub,
}));
vi.mock('@/components/workflows/approval-wizard-dialog', () => ({ default: Stub }));
vi.mock('@/components/concepts/request-concept-action-dialog', () => ({
  RequestConceptActionDialog: Stub,
}));
vi.mock('@/components/comments', () => ({ CommentSidebar: Stub }));
vi.mock('@/components/semantic/status-progress-bar', () => ({ StatusProgressBar: Stub }));

import ConceptDetailView from './concept-detail';

const IRI = 'http://example.org/concepts/Mixed';
const PARENT = 'http://example.org/concepts/Parent';

describe('ConceptDetailView label precedence', () => {
  beforeEach(() => {
    get.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/semantic-models/concepts/by-iri')) {
        return {
          data: {
            concept: {
              iri: IRI,
              label: 'RdfsEN',
              concept_type: 'concept',
              status: 'draft',
              labels: { en: 'PrefEN', pt: 'RdfsPT' },
              label_maps: { prefLabel: { en: 'PrefEN' }, rdfsLabel: { pt: 'RdfsPT' } },
              linked_label_maps: { [PARENT]: { prefLabel: { en: 'ParentPref' } } },
              comments: {},
              parent_concepts: [PARENT],
              child_concepts: [],
            },
          },
        };
      }
      return { data: {} };
    });
  });

  it('shows prefLabel over rdfs:label, in title and hierarchy', async () => {
    render(
      <MemoryRouter initialEntries={[`/concepts/${encodeURIComponent(IRI)}`]}>
        <Routes>
          <Route path="/concepts/*" element={<ConceptDetailView />} />
        </Routes>
      </MemoryRouter>,
    );
    const summary = await screen.findByTestId('concept-summary-panel');
    expect(await within(summary).findByText('PrefEN')).toBeInTheDocument();
    expect(screen.queryByText('RdfsPT')).toBeNull();
    const hierarchy = screen
      .getByTestId('concept-panels')
      .querySelector<HTMLElement>('[data-panel="hierarchy"]')!;
    expect(within(hierarchy).getByText('ParentPref')).toBeInTheDocument();
    expect(within(hierarchy).queryByText('Parent', { selector: '.cursor-pointer' })).toBeNull();
  });
});
