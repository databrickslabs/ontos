/**
 * Concept detail page layout: a single-column panel stack (one panel per row)
 * that opens with the ConceptSummaryPanel and always ends with Metadata (Turtle
 * directly above it, Advanced only). Synonyms / examples live inside the
 * summary, the "Request" button opens the action dialog, and the SPARQL
 * launcher is gone (it moved to the Explore page).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
vi.mock('@/components/comments', () => ({ CommentSidebar: Stub }));
vi.mock('@/components/semantic/status-progress-bar', () => ({
  StatusProgressBar: ({ status }: { status: string }) => (
    <div data-testid="concept-status">{status}</div>
  ),
}));
// Native stand-in for the Radix-based action dialog: records its props and
// renders a marker only while open.
const { dialogProps } = vi.hoisted(() => ({ dialogProps: [] as Array<Record<string, unknown>> }));
vi.mock('@/components/concepts/request-concept-action-dialog', () => ({
  RequestConceptActionDialog: (props: Record<string, unknown>) => {
    dialogProps.push(props);
    return props.open ? <div data-testid="request-action-dialog" /> : null;
  },
}));

import ConceptDetailView from './concept-detail';

const IRI = 'http://example.org/concepts/Customer';
const SCHEME = 'urn:scheme:sales';

function concept(overrides: Record<string, unknown> = {}) {
  return {
    iri: IRI,
    label: 'Customer',
    concept_type: 'concept',
    status: 'draft',
    source_context: SCHEME,
    labels: {},
    comments: { en: 'A party that buys goods.' },
    parent_concepts: [],
    child_concepts: [],
    synonyms: ['Client', 'Buyer'],
    examples: ['Retail shopper', 'Wholesale account'],
    ...overrides,
  };
}

let current = concept();

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/concepts/${encodeURIComponent(IRI)}`]}>
      <Routes>
        <Route path="/concepts/*" element={<ConceptDetailView />} />
      </Routes>
    </MemoryRouter>,
  );
}

const EXPECTED_ORDER = [
  'definition',
  'ownership',
  'details',
  'hierarchy',
  'linked-assets',
  'version-history',
  'relations',
  'turtle',
  'metadata',
];

async function panelOrder() {
  const stack = await screen.findByTestId('concept-panels');
  const summary = within(stack).getByTestId('concept-summary-panel');
  const panels = Array.from(stack.querySelectorAll<HTMLElement>('[data-panel]'));
  return { stack, summary, names: panels.map((p) => p.dataset.panel) };
}

describe('ConceptDetailView layout', () => {
  beforeEach(() => {
    current = concept();
    dialogProps.length = 0;
    get.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/semantic-models/concepts/by-iri')) {
        return { data: { concept: current } };
      }
      if (url.startsWith('/api/knowledge/collections')) {
        return { data: { collections: [{ iri: SCHEME, label: 'Sales', is_editable: true }] } };
      }
      if (url.startsWith('/api/semantic-models/concepts/version')) {
        return { data: { current_version: 1 } };
      }
      return { data: {} };
    });
  });

  afterEach(() => {
    document.documentElement.removeAttribute('data-mode');
  });

  for (const mode of ['simple', 'advanced'] as const) {
    it(`stacks panels in a single column, summary first and Metadata last (${mode})`, async () => {
      document.documentElement.setAttribute('data-mode', mode);
      renderPage();
      const { stack, summary, names } = await panelOrder();

      // Single column: a flex column stack, no multi-column grid.
      expect(stack.className).toContain('flex-col');
      expect(stack.className).not.toMatch(/grid-cols-2/);
      // Summary panel is the very first panel.
      expect(stack.firstElementChild).toBe(summary);
      expect(names).toEqual(EXPECTED_ORDER);
      // Turtle is the Advanced-only panel directly above Metadata.
      const turtle = stack.querySelector('[data-panel="turtle"]')!;
      expect(turtle.className).toContain('adv-only');
      expect(stack.lastElementChild).toBe(stack.querySelector('[data-panel="metadata"]'));
    });
  }

  it('shows synonyms and examples inside the summary panel', async () => {
    renderPage();
    const summary = await screen.findByTestId('concept-summary-panel');
    const synonyms = within(summary).getByTestId('concept-summary-synonyms');
    expect(within(synonyms).getByText('Client')).toBeInTheDocument();
    expect(within(synonyms).getByText('Buyer')).toBeInTheDocument();
    const examples = within(summary).getByTestId('concept-summary-examples');
    expect(within(examples).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Retail shopper',
      'Wholesale account',
    ]);
    // Title, status chain and IRI chip are hosted by the summary too.
    expect(within(summary).getByText('Customer')).toBeInTheDocument();
    expect(within(summary).getByTestId('concept-status')).toHaveTextContent('draft');
    expect(within(summary).getByTestId('concept-summary-iri')).toHaveTextContent(IRI);
  });

  it('hides the synonyms / examples rows when the concept has none', async () => {
    current = concept({ synonyms: [], examples: [] });
    renderPage();
    const summary = await screen.findByTestId('concept-summary-panel');
    expect(within(summary).queryByTestId('concept-summary-synonyms')).toBeNull();
    expect(within(summary).queryByTestId('concept-summary-examples')).toBeNull();
  });

  it('opens the request action dialog from the Request button', async () => {
    renderPage();
    await screen.findByTestId('concept-summary-panel');
    expect(screen.queryByTestId('request-action-dialog')).toBeNull();

    await userEvent.click(await screen.findByRole('button', { name: /request/i }));

    expect(await screen.findByTestId('request-action-dialog')).toBeInTheDocument();
    const last = dialogProps[dialogProps.length - 1];
    expect(last.open).toBe(true);
    expect(last.currentStatus).toBe('draft');
    expect(last.transitions).toEqual([
      expect.objectContaining({ status: 'under_review', action: 'submit-review' }),
    ]);
    expect(last.newVersion).toEqual(expect.objectContaining({ disabled: true }));
  });

  it('does not render a SPARQL button on the concept page', async () => {
    renderPage();
    await screen.findByTestId('concept-summary-panel');
    expect(screen.queryByRole('button', { name: /sparql/i })).toBeNull();
  });
});
