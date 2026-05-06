import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';

// ---------------------------------------------------------------------------
// Mocks
//
// We isolate the redirect logic from the heavy children -- ConceptsTab,
// dialogs, the filter panel, and the API. The redirect is the only behaviour
// under test here, so we render the smallest realistic shell.
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: any) => {
      if (options && typeof options === 'object' && 'defaultValue' in options) {
        return options.defaultValue as string;
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    hasPermission: () => true,
    fetchPermissions: vi.fn(),
    fetchAvailableRoles: vi.fn(),
  }),
}));

vi.mock('@/stores/breadcrumb-store', () => ({
  default: () => () => undefined,
}));

vi.mock('@/stores/knowledge-graph-store', () => ({
  useKnowledgeGraphStore: (selector: any) =>
    selector({
      refreshNonce: 0,
      lastReason: null,
      bumpRefreshNonce: vi.fn(),
    }),
}));

vi.mock('@/stores/glossary-preferences-store', () => ({
  useGlossaryPreferencesStore: () => ({
    hiddenSources: [],
    groupBySource: false,
    showProperties: false,
    groupByDomain: false,
    isFilterExpanded: false,
    expandedConceptGroups: [],
    conceptListScrollTop: 0,
    conceptListSearch: '',
    toggleSource: vi.fn(),
    selectAllSources: vi.fn(),
    selectNoneSources: vi.fn(),
    setGroupBySource: vi.fn(),
    setShowProperties: vi.fn(),
    setGroupByDomain: vi.fn(),
    setFilterExpanded: vi.fn(),
    setExpandedConceptGroups: vi.fn(),
    toggleConceptGroup: vi.fn(),
    setConceptListScrollTop: vi.fn(),
    setConceptListSearch: vi.fn(),
  }),
}));

vi.mock('@/components/knowledge', () => ({
  ConceptsTab: () => null,
  CollectionEditorDialog: () => null,
  ConceptEditorDialog: () => null,
  GlossaryFilterPanel: () => null,
  ImportConceptsDialog: () => null,
}));

// Stub out the global fetch so initial data loads resolve to empty. The
// redirect happens before these matter, but we do not want unhandled
// promises spamming the test console.
beforeEach(() => {
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({}),
    text: async () => '',
  })) as unknown as typeof fetch;
});

import BusinessTermsView from './business-terms';

function renderAt(initialEntry: string) {
  let observed = { pathname: '', search: '' };
  function Probe() {
    const location = useLocation();
    observed = { pathname: location.pathname, search: location.search };
    return null;
  }
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/concepts/browser" element={<><BusinessTermsView /><Probe /></>} />
        <Route
          path="/concepts/browser/:iri"
          element={<><div data-testid="detail-route" /><Probe /></>}
        />
      </Routes>
    </MemoryRouter>,
  );
  return () => observed;
}

describe('BusinessTermsView legacy ?concept= redirect', () => {
  it('redirects ?concept=IRI to /concepts/browser/:iri', async () => {
    const iri = 'https://example.org/onto#Customer';
    const observe = renderAt(`/concepts/browser?concept=${encodeURIComponent(iri)}`);

    await waitFor(() => {
      expect(observe().pathname).toBe(`/concepts/browser/${encodeURIComponent(iri)}`);
    });
  });

  it('does not redirect when no ?concept= is present', async () => {
    const observe = renderAt('/concepts/browser');
    // Give react a tick to settle effects.
    await new Promise((r) => setTimeout(r, 10));
    expect(observe().pathname).toBe('/concepts/browser');
  });
});
