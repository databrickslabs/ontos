import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { SortingState } from '@tanstack/react-table';

// Table state for the Enrich "Map" coverage table (components/enrich/
// coverage-matrix.tsx). Persisted so the chosen sort, page size and search
// survive navigating away from Enrich and reloading the page.

export const DEFAULT_COVERAGE_SORTING: SortingState = [{ id: 'scheme', desc: false }];
export const DEFAULT_COVERAGE_PAGE_SIZE = 10;

interface EnrichCoverageTableState {
  search: string;
  sorting: SortingState;
  pageSize: number;
  setSearch: (search: string) => void;
  setSorting: (sorting: SortingState) => void;
  setPageSize: (pageSize: number) => void;
  reset: () => void;
}

export const useEnrichCoverageTableStore = create<EnrichCoverageTableState>()(
  persist(
    (set) => ({
      search: '',
      sorting: DEFAULT_COVERAGE_SORTING,
      pageSize: DEFAULT_COVERAGE_PAGE_SIZE,
      setSearch: (search) => set({ search }),
      setSorting: (sorting) => set({ sorting }),
      setPageSize: (pageSize) => set({ pageSize }),
      reset: () =>
        set({
          search: '',
          sorting: DEFAULT_COVERAGE_SORTING,
          pageSize: DEFAULT_COVERAGE_PAGE_SIZE,
        }),
    }),
    {
      name: 'ucapp-enrich-coverage-table',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        search: state.search,
        sorting: state.sorting,
        pageSize: state.pageSize,
      }),
    },
  ),
);
