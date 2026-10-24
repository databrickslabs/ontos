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

import { useExploreConcepts, useExploreSessionStore } from './use-explore-concepts';

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  showProperties = false;
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
