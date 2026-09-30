import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

// The "Group by" lens re-organizes the same chips/terms under dimension
// headers. It is a LENS (how things are grouped), not a second filter --
// filtering is driven independently by `hiddenSources` (see below).
export type GroupByDimension = 'none' | 'scheme' | 'source' | 'domain';

interface GlossaryPreferencesState {
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
    }),
    {
      name: 'glossary-preferences-storage',
      storage: createJSONStorage(() => localStorage),
      // v1 introduced the `groupByDimension` lens. Older persisted state only
      // has the boolean flags, so derive the lens from them. Legacy
      // `groupBySource` was source_context (scheme) grouping, so it maps to
      // 'scheme' (NOT 'source' — 'source' now means the originating file).
      version: 1,
      migrate: (persisted: any, version: number) => {
        if (!persisted) return persisted;
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
        // Scroll position is intentionally NOT persisted across reloads --
        // it is only kept across in-app navigation while the store stays
        // in memory. Persisting it would scroll users to stale offsets
        // after a refresh when the underlying data changed.
        conceptListSearch: state.conceptListSearch,
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
