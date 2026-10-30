import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

import type { LineageDirection } from '@/components/lineage/lineage-toolbar';
import type { LineageDetail } from '@/components/lineage/layout';
import { DEFAULT_VIEW_OPTIONS } from '@/components/lineage/highlight';
import type { ViewOptions } from '@/components/lineage/highlight';

/**
 * Business lineage view preferences, persisted per browser and shared across
 * entities. Per-graph state (selection, zoom/pan, dragged positions) is not
 * stored. Embedded views that pin direction/depth (e.g. impact analysis) keep
 * local state and never read or write this store.
 */
interface LineagePreferencesState {
  direction: LineageDirection;
  maxDepth: number;
  detail: LineageDetail;
  viewOptions: ViewOptions;
  /** With a selection: only the path (true) or everything, rest dimmed (false) */
  focusMode: boolean;

  setDirection: (direction: LineageDirection) => void;
  setMaxDepth: (maxDepth: number) => void;
  setDetail: (detail: LineageDetail) => void;
  setViewOptions: (viewOptions: ViewOptions) => void;
  setFocusMode: (focusMode: boolean) => void;
}

export const DEFAULT_LINEAGE_PREFERENCES = {
  direction: 'both' as LineageDirection,
  maxDepth: 2,
  detail: 'structure' as LineageDetail,
  viewOptions: DEFAULT_VIEW_OPTIONS,
  focusMode: true,
};

export const useLineagePreferencesStore = create<LineagePreferencesState>()(
  persist(
    (set) => ({
      ...DEFAULT_LINEAGE_PREFERENCES,

      setDirection: (direction) => set({ direction }),
      setMaxDepth: (maxDepth) => set({ maxDepth }),
      setDetail: (detail) => set({ detail }),
      setViewOptions: (viewOptions) => set({ viewOptions }),
      setFocusMode: (focusMode) => set({ focusMode }),
    }),
    {
      name: 'lineage-preferences',
      storage: createJSONStorage(() => localStorage),
      version: 1,
      partialize: (state) => ({
        direction: state.direction,
        maxDepth: state.maxDepth,
        detail: state.detail,
        viewOptions: state.viewOptions,
        focusMode: state.focusMode,
      }),
      // Deep-merge view options so options added later get their defaults
      merge: (persisted, current) => {
        const p = (persisted || {}) as Partial<LineagePreferencesState>;
        return {
          ...current,
          ...p,
          viewOptions: {
            ...DEFAULT_VIEW_OPTIONS,
            ...p.viewOptions,
            layers: { ...DEFAULT_VIEW_OPTIONS.layers, ...p.viewOptions?.layers },
            edges: { ...DEFAULT_VIEW_OPTIONS.edges, ...p.viewOptions?.edges },
          },
        };
      },
    },
  ),
);
