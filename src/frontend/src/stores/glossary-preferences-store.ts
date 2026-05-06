import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

interface GlossaryPreferencesState {
  // Source filtering - stores hidden sources
  hiddenSources: string[];
  
  // Grouping
  groupBySource: boolean;
  
  // Show properties toggle
  showProperties: boolean;
  
  // Group properties by domain
  groupByDomain: boolean;
  
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
  selectAllSources: () => void;
  selectNoneSources: (allSources: string[]) => void;
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
      groupBySource: false,
      showProperties: false,
      groupByDomain: false,
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

      selectAllSources: () => {
        // Clear all hidden sources - shows all
        set({ hiddenSources: [] });
      },

      selectNoneSources: (allSources: string[]) => {
        // Hide all sources
        set({ hiddenSources: [...allSources] });
      },

      setGroupBySource: (enabled: boolean) => {
        set({ groupBySource: enabled });
      },

      setShowProperties: (enabled: boolean) => {
        set({ showProperties: enabled });
      },

      setGroupByDomain: (enabled: boolean) => {
        set({ groupByDomain: enabled });
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
      partialize: (state) => ({
        hiddenSources: state.hiddenSources,
        groupBySource: state.groupBySource,
        showProperties: state.showProperties,
        groupByDomain: state.groupByDomain,
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
    setGroupBySource: state.setGroupBySource,
    setShowProperties: state.setShowProperties,
    setGroupByDomain: state.setGroupByDomain,
  }));
