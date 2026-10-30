import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

// The hook must request the grouped endpoints WITHOUT include_system by default
// (system ontologies hidden) and WITH include_system=true once the session
// toggle is on, so List / Tree / Graph (all fed by this hook) respect it.

let showProperties = false;
vi.mock('@/stores/glossary-preferences-store', () => ({
  useGlossaryPreferencesStore: (selector: any) => selector({ showProperties, hiddenSources: [] }),
}));

vi.mock('@/stores/knowledge-graph-store', () => ({
  useKnowledgeGraphStore: (selector: any) => selector({ refreshNonce: 0 }),
}));

// The system-ontology toggle only takes effect in Advanced (L) mode.
let conceptMode: 'simple' | 'advanced' = 'advanced';
vi.mock('@/components/concepts/mode-switch', () => ({
  useConceptMode: () => [conceptMode, vi.fn()],
}));

import { useExploreConcepts, useExploreSessionStore } from './use-explore-concepts';

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  showProperties = false;
  conceptMode = 'advanced';
  useExploreSessionStore.setState({ showSystemSources: false });
  fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }));
  global.fetch = fetchMock as unknown as typeof fetch;
});

const calledUrls = () => fetchMock.mock.calls.map((c) => String(c[0]));

describe('useExploreConcepts system-ontology toggle', () => {
  it('excludes system ontologies by default and opts in when the toggle is on', async () => {
    renderHook(() => useExploreConcepts());
    await waitFor(() =>
      expect(calledUrls()).toContain('/api/semantic-models/concepts-grouped'),
    );
    expect(calledUrls().some((u) => u.includes('include_system'))).toBe(false);

    fetchMock.mockClear();
    act(() => useExploreSessionStore.getState().setShowSystemSources(true));
    await waitFor(() =>
      expect(calledUrls()).toContain('/api/semantic-models/concepts-grouped?include_system=true'),
    );
  });

  it('applies the toggle to properties-grouped as well', async () => {
    showProperties = true;
    useExploreSessionStore.setState({ showSystemSources: true });
    renderHook(() => useExploreConcepts());
    await waitFor(() =>
      expect(calledUrls()).toContain('/api/semantic-models/properties-grouped?include_system=true'),
    );
  });

  it('toggling after the first load filters client-side without a reload', async () => {
    const payload = (includeSystem: boolean) => ({
      grouped_concepts: {
        'my-scheme': [{ iri: 'urn:a', label: 'A', source_context: 'my-scheme', concept_type: 'concept' }],
        ...(includeSystem
          ? { 'ontos-ontology': [{ iri: 'urn:s', label: 'S', source_context: 'ontos-ontology', concept_type: 'class' }] }
          : {}),
      },
      system_sources: ['ontos-ontology'],
    });
    fetchMock.mockImplementation(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => (String(url).includes('concepts-grouped') ? payload(String(url).includes('include_system')) : {}),
    }));

    const { result } = renderHook(() => useExploreConcepts());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(Object.keys(result.current.groupedConcepts)).toEqual(['my-scheme']);

    act(() => useExploreSessionStore.getState().setShowSystemSources(true));
    await waitFor(() => expect(Object.keys(result.current.groupedConcepts)).toContain('ontos-ontology'));
    expect(result.current.isLoading).toBe(false);

    fetchMock.mockClear();
    act(() => useExploreSessionStore.getState().setShowSystemSources(false));
    expect(Object.keys(result.current.groupedConcepts)).toEqual(['my-scheme']);
    expect(result.current.filteredConcepts.map((c) => c.iri)).toEqual(['urn:a']);
    act(() => useExploreSessionStore.getState().setShowSystemSources(true));
    expect(Object.keys(result.current.groupedConcepts)).toContain('ontos-ontology');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('useExploreConcepts system-ontology toggle in Simple mode', () => {
  const payload = (includeSystem: boolean) => ({
    grouped_concepts: {
      'my-scheme': [{ iri: 'urn:a', label: 'A', source_context: 'my-scheme', concept_type: 'concept' }],
      ...(includeSystem
        ? { 'ontos-ontology': [{ iri: 'urn:s', label: 'S', source_context: 'ontos-ontology', concept_type: 'class' }] }
        : {}),
    },
    system_sources: ['ontos-ontology'],
  });
  const mockPayload = () =>
    fetchMock.mockImplementation(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => (String(url).includes('concepts-grouped') ? payload(String(url).includes('include_system')) : {}),
    }));

  it('ignores a stored "on" flag in S mode: no include_system fetch, system groups hidden', async () => {
    conceptMode = 'simple';
    showProperties = true;
    useExploreSessionStore.setState({ showSystemSources: true });
    mockPayload();
    const { result } = renderHook(() => useExploreConcepts());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(calledUrls().some((u) => u.includes('include_system'))).toBe(false);
    expect(Object.keys(result.current.groupedConcepts)).toEqual(['my-scheme']);
    // The stored choice itself is untouched.
    expect(useExploreSessionStore.getState().showSystemSources).toBe(true);
  });

  it('hides system groups on switching L to S and restores them on switching back', async () => {
    useExploreSessionStore.setState({ showSystemSources: true });
    mockPayload();
    const { result, rerender } = renderHook(() => useExploreConcepts());
    await waitFor(() => expect(Object.keys(result.current.groupedConcepts)).toContain('ontos-ontology'));

    conceptMode = 'simple';
    rerender();
    expect(Object.keys(result.current.groupedConcepts)).toEqual(['my-scheme']);

    conceptMode = 'advanced';
    rerender();
    expect(Object.keys(result.current.groupedConcepts)).toContain('ontos-ontology');
  });
});

describe('useExploreConcepts available sources', () => {
  const load = (collection: Record<string, unknown>) => {
    fetchMock.mockImplementation(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => {
        const u = String(url);
        if (u.includes('/api/knowledge/collections')) return { collections: [collection] };
        if (u.includes('concepts-grouped')) {
          return {
            grouped_concepts: {
              'Demo Data': [{ iri: 'urn:d1', label: 'D1', source_context: 'Demo Data', concept_type: 'concept' }],
            },
          };
        }
        return {};
      },
    }));
    return renderHook(() => useExploreConcepts());
  };

  it('lists an editable scheme under its source_key, once', async () => {
    const { result } = load({ iri: 'urn:demo', label: 'Demo', is_editable: true, source_key: 'Demo Data' });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.availableSources.filter((s) => s === 'Demo Data')).toHaveLength(1);
    expect(result.current.availableSources).not.toContain('urn:demo');
  });

  it('falls back to the stripped IRI when source_key is missing', async () => {
    const { result } = load({ iri: 'urn:glossary:finance', label: 'Finance', is_editable: true });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.availableSources).toEqual(['Demo Data', 'finance']);
  });
});
