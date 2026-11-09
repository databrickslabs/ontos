import { describe, it, expect, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import {
  useEnrichCoverageTableStore,
  DEFAULT_COVERAGE_SORTING,
  DEFAULT_COVERAGE_PAGE_SIZE,
} from './enrich-coverage-table-store';

const STORAGE_NAME = 'ucapp-enrich-coverage-table';

const persisted = () => JSON.parse(localStorage.getItem(STORAGE_NAME) ?? 'null')?.state;

beforeEach(() => {
  localStorage.clear();
  act(() => useEnrichCoverageTableStore.getState().reset());
});

describe('enrich coverage table store', () => {
  it('defaults to name ascending, page size 10 and no search', () => {
    const s = useEnrichCoverageTableStore.getState();
    expect(s.sorting).toEqual([{ id: 'scheme', desc: false }]);
    expect(DEFAULT_COVERAGE_SORTING).toEqual([{ id: 'scheme', desc: false }]);
    expect(s.pageSize).toBe(10);
    expect(DEFAULT_COVERAGE_PAGE_SIZE).toBe(10);
    expect(s.search).toBe('');
  });

  it('persists search, sorting and page size to localStorage', () => {
    act(() => {
      const s = useEnrichCoverageTableStore.getState();
      s.setSearch('logistics');
      s.setSorting([{ id: 'coverage', desc: true }]);
      s.setPageSize(30);
    });
    expect(persisted()).toEqual({
      search: 'logistics',
      sorting: [{ id: 'coverage', desc: true }],
      pageSize: 30,
    });
  });

  it('persists only the table state (no actions)', () => {
    act(() => useEnrichCoverageTableStore.getState().setSearch('x'));
    expect(Object.keys(persisted()).sort()).toEqual(['pageSize', 'search', 'sorting']);
  });

  it('rehydrates stored state (survives a reload)', async () => {
    localStorage.setItem(
      STORAGE_NAME,
      JSON.stringify({
        state: { search: 'events', sorting: [{ id: 'concepts', desc: true }], pageSize: 20 },
        version: 0,
      }),
    );
    await act(async () => {
      await useEnrichCoverageTableStore.persist.rehydrate();
    });
    const s = useEnrichCoverageTableStore.getState();
    expect(s.search).toBe('events');
    expect(s.sorting).toEqual([{ id: 'concepts', desc: true }]);
    expect(s.pageSize).toBe(20);
  });

  it('reset restores the defaults', () => {
    act(() => {
      const s = useEnrichCoverageTableStore.getState();
      s.setSearch('a');
      s.setPageSize(50);
      s.reset();
    });
    const s = useEnrichCoverageTableStore.getState();
    expect(s.search).toBe('');
    expect(s.pageSize).toBe(10);
    expect(s.sorting).toEqual(DEFAULT_COVERAGE_SORTING);
  });
});
