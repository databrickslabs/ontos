import { create } from 'zustand';

/**
 * Lightweight cross-view broadcast channel for the Concepts feature.
 *
 * Any view (Concepts, Graph, Settings/RDF Sources, Ontology Generator,
 * Semantic Links manager, …) that mutates collections, concepts, semantic
 * links, or rebuilds the knowledge graph should call `bumpRefreshNonce()`.
 * Views that show derived data (collection lists, concept groupings,
 * filter chips, etc.) can subscribe to `refreshNonce` in a `useEffect`
 * dependency array to refetch automatically.
 */
interface KnowledgeGraphState {
  refreshNonce: number;
  lastReason: string | null;
  bumpRefreshNonce: (reason?: string) => void;
}

export const useKnowledgeGraphStore = create<KnowledgeGraphState>((set) => ({
  refreshNonce: 0,
  lastReason: null,
  bumpRefreshNonce: (reason?: string) =>
    set((state) => ({
      refreshNonce: state.refreshNonce + 1,
      lastReason: reason ?? null,
    })),
}));
