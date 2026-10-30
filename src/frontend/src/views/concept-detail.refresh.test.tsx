/**
 * The concept detail page refetches the concept when another view (e.g. the
 * workflow approval-response dialog) bumps the knowledge-graph refresh nonce,
 * so a reviewer staying on the page sees the new status without reloading.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
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
vi.mock('@/components/semantic/status-progress-bar', () => ({
  StatusProgressBar: ({ status }: { status: string }) => (
    <div data-testid="concept-status">{status}</div>
  ),
}));

import { useKnowledgeGraphStore } from '@/stores/knowledge-graph-store';
import ConceptDetailView from './concept-detail';

const IRI = 'http://example.org/concepts/Customer';
const CONCEPT_URL = `/api/semantic-models/concepts/by-iri?iri=${encodeURIComponent(IRI)}`;

function concept(status: string) {
  return {
    iri: IRI,
    label: 'Customer',
    concept_type: 'concept',
    status,
    labels: {},
    comments: {},
    parent_concepts: [],
    child_concepts: [],
  };
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

describe('ConceptDetailView knowledge-graph refresh', () => {
  let status = 'under_review';

  beforeEach(() => {
    status = 'under_review';
    useKnowledgeGraphStore.setState({ refreshNonce: 0, lastReason: null });
    get.mockImplementation(async (url: string) => {
      if (url === CONCEPT_URL) return { data: { concept: concept(status) } };
      return { data: {} };
    });
  });

  const conceptFetches = () => get.mock.calls.filter(([u]) => u === CONCEPT_URL).length;

  it('refetches the concept and shows the new status after an external nonce bump', async () => {
    renderPage();
    expect(await screen.findByTestId('concept-status')).toHaveTextContent('under_review');
    expect(conceptFetches()).toBe(1);

    // A reviewer approves the concept from the approval-response dialog.
    status = 'approved';
    act(() => {
      useKnowledgeGraphStore.getState().bumpRefreshNonce('concept-approval-decision');
    });

    await waitFor(() =>
      expect(screen.getByTestId('concept-status')).toHaveTextContent('approved'),
    );
    expect(conceptFetches()).toBe(2);
    // Quiet refetch: the page stays rendered (no full-page loader swap).
    expect(screen.getByTestId('concept-status')).toBeInTheDocument();
  });

  it('does not refetch on mount for a pre-existing nonce value', async () => {
    useKnowledgeGraphStore.setState({ refreshNonce: 7, lastReason: 'earlier' });
    renderPage();
    await screen.findByTestId('concept-status');
    // Give any stray effect a tick to run.
    await act(async () => {});
    expect(conceptFetches()).toBe(1);
  });
});
