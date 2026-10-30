import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

// The "Group by" lens re-organizes the same chips/terms under dimension
// headers. It is a LENS (how things are grouped), not a second filter --
// filtering is driven independently by `hiddenSources` (see below).
export type GroupByDimension = 'none' | 'scheme' | 'source' | 'domain';

// Sort order of the scheme/source chips in the filter panel (List tab).
export type SourceSortMode = 'name' | 'size';

// Cytoscape layout used by the Graph tab. Mirrors `LayoutType` in
// components/semantic-models/knowledge-graph.tsx.
export type GraphLayout = 'circle' | 'cose' | 'grid' | 'breadthfirst' | 'concentric';

// User-facing Graph tab display options. Persisted so the chosen layout and
// toggles survive reloads. Transient graph state (selection, zoom/pan,
// fullscreen, loading) is deliberately NOT part of this.
export interface GraphOptions {
  graphLayout: GraphLayout;
  graphShowDomainBoxes: boolean;
  graphShowNodeLabels: boolean;
  graphShowEdgeLabels: boolean;
  graphNodeSize: number;
  graphSpacing: number;
}

export const DEFAULT_GRAPH_OPTIONS: GraphOptions = {
  graphLayout: 'cose',
  graphShowDomainBoxes: true,
  graphShowNodeLabels: false,
  graphShowEdgeLabels: false,
  graphNodeSize: 24,
  graphSpacing: 80,
};

interface GlossaryPreferencesState extends GraphOptions {
  // Source filtering - stores hidden sources
  hiddenSources: string[];

  // Grouping lens: single source of truth for how terms are re-organized.
  groupByDimension: GroupByDimension;

  // Legacy grouping booleans, kept in sync with `groupByDimension` so that
  // existing call sites (ConceptsTab / filter panel) keep working. Derived
  // from the lens on every `setGroupByDimension`. Prefer the lens for new code.
  groupBySource: boolean;

  // Show properties toggle
  showProperties: boolean;

  // Group properties by domain
  groupByDomain: boolean;

  // Backs the 'source' grouping dimension. Groups concepts by their originating
  // FILE (source_file). A single scheme can be merged from multiple files, so
  // 'source' (file) splits a merged scheme back into its per-file origins,
  // whereas 'scheme' (groupBySource, keyed on source_context) keeps the scheme
  // whole. Kept in sync with `groupByDimension`; mutually exclusive with
  // groupBySource / groupByDomain.
  groupByFile: boolean;

  // UI state
  isFilterExpanded: boolean;

  // Concepts list-view UI state. Persisted so the user's tree exploration
  // survives navigation into a concept detail page and back, plus full
  // page reloads.
  expandedConceptGroups: string[];
  conceptListScrollTop: number;
  conceptListSearch: string;

  // Filter panel chip sort order (Name / Size). Persisted.
  sourceSortMode: SourceSortMode;
  
  // Actions
  toggleSource: (source: string) => void;
  /** Set the hidden-sources set in one shot (idempotent — no per-source churn).
   *  Used by the ?source= deep-link so it doesn't loop by reacting to its own
   *  per-toggle mutations. */
  setHiddenSources: (sources: string[]) => void;
  selectAllSources: () => void;
  selectNoneSources: (allSources: string[]) => void;
  setGroupByDimension: (dimension: GroupByDimension) => void;
  setGroupBySource: (enabled: boolean) => void;
  setShowProperties: (enabled: boolean) => void;
  setGroupByDomain: (enabled: boolean) => void;
  isSourceVisible: (source: string) => boolean;
  setFilterExpanded: (expanded: boolean) => void;
  setExpandedConceptGroups: (groups: string[]) => void;
  toggleConceptGroup: (group: string) => void;
  setConceptListScrollTop: (scrollTop: number) => void;
  setConceptListSearch: (search: string) => void;
  setSourceSortMode: (mode: SourceSortMode) => void;
  /** Set one Graph tab option. Accepts a value or an updater of the current value. */
  setGraphOption: <K extends keyof GraphOptions>(
    key: K,
    value: GraphOptions[K] | ((prev: GraphOptions[K]) => GraphOptions[K]),
  ) => void;
}

export const useGlossaryPreferencesStore = create<GlossaryPreferencesState>()(
  persist(
    (set, get) => ({
      hiddenSources: [],
      groupByDimension: 'none',
      groupBySource: false,
      showProperties: false,
      groupByDomain: false,
      groupByFile: false,
      isFilterExpanded: true,
      expandedConceptGroups: ['root'],
      conceptListScrollTop: 0,
      conceptListSearch: '',
      sourceSortMode: 'name',
      ...DEFAULT_GRAPH_OPTIONS,

      toggleSource: (source: string) => {
        set((state) => {
          const isCurrentlyHidden = state.hiddenSources.includes(source);
          if (isCurrentlyHidden) {
            // Remove from hidden (show it)
            return {
              hiddenSources: state.hiddenSources.filter((s) => s !== source),
            };
          } else {
            // Add to hidden
            return {
              hiddenSources: [...state.hiddenSources, source],
            };
          }
        });
      },

      setHiddenSources: (sources: string[]) => {
        // Idempotent single set — guard against a no-op write so subscribers
        // (and any effect keyed on hiddenSources) don't churn.
        set((state) => {
          const next = Array.from(new Set(sources)).sort();
          const cur = [...state.hiddenSources].sort();
          if (next.length === cur.length && next.every((s, i) => s === cur[i])) {
            return state; // unchanged — no re-render/loop
          }
          return { hiddenSources: sources };
        });
      },

      selectAllSources: () => {
        // Clear all hidden sources - shows all
        set({ hiddenSources: [] });
      },

      selectNoneSources: (allSources: string[]) => {
        // Hide all sources
        set({ hiddenSources: [...allSources] });
      },

      setGroupByDimension: (dimension: GroupByDimension) => {
        // The lens is canonical; derive the legacy booleans so consumers that
        // still read groupBySource/groupByFile/groupByDomain (ConceptsTab tree
        // builder) stay consistent. The two source-ish dimensions now DIVERGE:
        //   'scheme' -> groupBySource, keyed on source_context (the scheme IRI).
        //   'source' -> groupByFile,   keyed on source_file (originating file).
        // A merged scheme spans multiple files, so 'source' (file) splits it
        // into per-file groups while 'scheme' keeps it whole. The three grouping
        // booleans are mutually exclusive — exactly one (or none) is ever true.
        set({
          groupByDimension: dimension,
          groupBySource: dimension === 'scheme',
          groupByFile: dimension === 'source',
          groupByDomain: dimension === 'domain',
        });
      },

      setGroupBySource: (enabled: boolean) => {
        // Legacy scheme-grouping setter. Keeps the lens in sync; maps to the
        // 'scheme' dimension (source_context grouping).
        set({
          groupBySource: enabled,
          groupByFile: false,
          groupByDomain: false,
          groupByDimension: enabled ? 'scheme' : 'none',
        });
      },

      setShowProperties: (enabled: boolean) => {
        set({ showProperties: enabled });
      },

      setGroupByDomain: (enabled: boolean) => {
        // Keep the lens in sync when a legacy caller flips the boolean.
        set({
          groupByDomain: enabled,
          groupBySource: false,
          groupByFile: false,
          groupByDimension: enabled ? 'domain' : 'none',
        });
      },

      isSourceVisible: (source: string) => {
        return !get().hiddenSources.includes(source);
      },

      setFilterExpanded: (expanded: boolean) => {
        set({ isFilterExpanded: expanded });
      },

      setExpandedConceptGroups: (groups: string[]) => {
        set({ expandedConceptGroups: groups });
      },

      toggleConceptGroup: (group: string) => {
        set((state) => {
          const isExpanded = state.expandedConceptGroups.includes(group);
          if (isExpanded) {
            return {
              expandedConceptGroups: state.expandedConceptGroups.filter((g) => g !== group),
            };
          }
          return {
            expandedConceptGroups: [...state.expandedConceptGroups, group],
          };
        });
      },

      setConceptListScrollTop: (scrollTop: number) => {
        set({ conceptListScrollTop: scrollTop });
      },

      setConceptListSearch: (search: string) => {
        set({ conceptListSearch: search });
      },

      setSourceSortMode: (mode: SourceSortMode) => {
        set({ sourceSortMode: mode });
      },

      setGraphOption: (key, value) => {
        set((state) => {
          const next =
            typeof value === 'function'
              ? (value as (prev: GraphOptions[typeof key]) => GraphOptions[typeof key])(state[key])
              : value;
          return { [key]: next } as Partial<GlossaryPreferencesState>;
        });
      },
    }),
    {
      name: 'glossary-preferences-storage',
      storage: createJSONStorage(() => localStorage),
      // v1 introduced the `groupByDimension` lens. Older persisted state only
      // has the boolean flags, so derive the lens from them. Legacy
      // `groupBySource` was source_context (scheme) grouping, so it maps to
      // 'scheme' (NOT 'source' — 'source' now means the originating file).
      // v2 stops persisting `conceptListSearch` (session-only), and drops any
      // value stored by earlier versions so Explore no longer re-opens with a
      // stale search pre-filled.
      // v3 adds `sourceSortMode` and the Graph tab options (graph*). Older
      // states lack them; back-fill defaults so the stored shape is complete.
      version: 3,
      migrate: (persisted: any, version: number) => {
        if (!persisted) return persisted;
        if (version < 2) {
          delete persisted.conceptListSearch;
        }
        if (version < 1 && persisted.groupByDimension === undefined) {
          persisted.groupByDimension = persisted.groupBySource
            ? 'scheme'
            : persisted.groupByDomain
              ? 'domain'
              : 'none';
        }
        // Back-fill groupByFile for states persisted before the file lens
        // existed so the boolean is always defined alongside the dimension.
        // 'source' is the file-grouping dimension.
        if (persisted.groupByFile === undefined) {
          persisted.groupByFile = persisted.groupByDimension === 'source';
        }
        if (version < 3) {
          if (persisted.sourceSortMode !== 'name' && persisted.sourceSortMode !== 'size') {
            persisted.sourceSortMode = 'name';
          }
          for (const [key, def] of Object.entries(DEFAULT_GRAPH_OPTIONS)) {
            if (typeof persisted[key] !== typeof def) {
              persisted[key] = def;
            }
          }
        }
        return persisted;
      },
      partialize: (state) => ({
        hiddenSources: state.hiddenSources,
        groupByDimension: state.groupByDimension,
        groupBySource: state.groupBySource,
        showProperties: state.showProperties,
        groupByDomain: state.groupByDomain,
        groupByFile: state.groupByFile,
        isFilterExpanded: state.isFilterExpanded,
        expandedConceptGroups: state.expandedConceptGroups,
        sourceSortMode: state.sourceSortMode,
        graphLayout: state.graphLayout,
        graphShowDomainBoxes: state.graphShowDomainBoxes,
        graphShowNodeLabels: state.graphShowNodeLabels,
        graphShowEdgeLabels: state.graphShowEdgeLabels,
        graphNodeSize: state.graphNodeSize,
        graphSpacing: state.graphSpacing,
        // Scroll position and the Explore search text (`conceptListSearch`)
        // are intentionally NOT persisted across reloads -- they are only kept
        // across in-app navigation while the store stays in memory. Persisting
        // them would restore stale offsets / stale search text after a refresh.
      }),
    }
  )
);

// Export actions separately for easier usage
export const useGlossaryPreferencesActions = () =>
  useGlossaryPreferencesStore((state) => ({
    toggleSource: state.toggleSource,
    selectAllSources: state.selectAllSources,
    selectNoneSources: state.selectNoneSources,
    setGroupByDimension: state.setGroupByDimension,
    setGroupBySource: state.setGroupBySource,
    setShowProperties: state.setShowProperties,
    setGroupByDomain: state.setGroupByDomain,
  }));
