import { describe, it, expect, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useGlossaryPreferencesStore, DEFAULT_GRAPH_OPTIONS } from './glossary-preferences-store';

// Reset to the store's documented initial state before each test so cases do
// not leak grouping/filter state into one another.
beforeEach(() => {
  act(() => {
    useGlossaryPreferencesStore.setState({
      hiddenSources: [],
      groupByDimension: 'none',
      groupBySource: false,
      groupByFile: false,
      groupByDomain: false,
      showProperties: false,
      sourceSortMode: 'name',
      ...DEFAULT_GRAPH_OPTIONS,
    });
  });
});

describe('glossary preferences store', () => {
  describe('setGroupByDimension lens', () => {
    it('updates the lens field', () => {
      const { result } = renderHook(() => useGlossaryPreferencesStore());

      act(() => result.current.setGroupByDimension('scheme'));
      expect(result.current.groupByDimension).toBe('scheme');
    });

    it('keeps legacy booleans in sync with the lens (source = file, scheme = context)', () => {
      const { result } = renderHook(() => useGlossaryPreferencesStore());

      // 'source' now means the originating FILE -> backs groupByFile.
      act(() => result.current.setGroupByDimension('source'));
      expect(result.current.groupByFile).toBe(true);
      expect(result.current.groupBySource).toBe(false);
      expect(result.current.groupByDomain).toBe(false);

      // 'scheme' means the concept scheme (source_context) -> backs groupBySource.
      act(() => result.current.setGroupByDimension('scheme'));
      expect(result.current.groupBySource).toBe(true);
      expect(result.current.groupByFile).toBe(false);
      expect(result.current.groupByDomain).toBe(false);

      act(() => result.current.setGroupByDimension('domain'));
      expect(result.current.groupBySource).toBe(false);
      expect(result.current.groupByFile).toBe(false);
      expect(result.current.groupByDomain).toBe(true);

      act(() => result.current.setGroupByDimension('none'));
      expect(result.current.groupBySource).toBe(false);
      expect(result.current.groupByFile).toBe(false);
      expect(result.current.groupByDomain).toBe(false);
    });

    it('the three grouping booleans are mutually exclusive', () => {
      const { result } = renderHook(() => useGlossaryPreferencesStore());

      const exactlyOne = (a: boolean, b: boolean, c: boolean) =>
        [a, b, c].filter(Boolean).length <= 1;

      (['none', 'scheme', 'source', 'domain'] as const).forEach((dim) => {
        act(() => result.current.setGroupByDimension(dim));
        expect(
          exactlyOne(
            result.current.groupBySource,
            result.current.groupByFile,
            result.current.groupByDomain,
          ),
        ).toBe(true);
      });
    });

    it('legacy setters keep the lens consistent', () => {
      const { result } = renderHook(() => useGlossaryPreferencesStore());

      // setGroupBySource now backs the 'scheme' dimension (source_context).
      act(() => result.current.setGroupBySource(true));
      expect(result.current.groupByDimension).toBe('scheme');
      expect(result.current.groupByFile).toBe(false);

      act(() => result.current.setGroupByDomain(true));
      expect(result.current.groupByDimension).toBe('domain');
      expect(result.current.groupBySource).toBe(false);

      act(() => result.current.setGroupBySource(false));
      expect(result.current.groupByDimension).toBe('none');
    });
  });

  describe('easy-bar multi-select is OR/union', () => {
    // Mirrors the predicate the browse view uses: a term is shown when its
    // source_context is NOT hidden. hiddenSources is an exclusion list, so
    // selecting multiple sources reads as "show ANY selected" (union), never
    // an intersection.
    const ALL_SOURCES = ['Finance', 'Logistics', 'FIBO', 'Unassigned'];
    const isVisible = (source: string, hidden: string[]) => !hidden.includes(source);

    it('shows the union of selected sources, not the intersection', () => {
      const { result } = renderHook(() => useGlossaryPreferencesStore());

      // Narrow to {Finance, FIBO}: hide everything else.
      act(() => result.current.selectNoneSources(ALL_SOURCES));
      act(() => {
        result.current.toggleSource('Finance'); // un-hide
        result.current.toggleSource('FIBO');    // un-hide
      });

      const hidden = result.current.hiddenSources;
      // Either selected source alone is enough to be shown (OR semantics).
      expect(isVisible('Finance', hidden)).toBe(true);
      expect(isVisible('FIBO', hidden)).toBe(true);
      // Unselected peers stay hidden.
      expect(isVisible('Logistics', hidden)).toBe(false);
      expect(isVisible('Unassigned', hidden)).toBe(false);
    });

    it('selectAllSources clears the exclusion list (everything visible)', () => {
      const { result } = renderHook(() => useGlossaryPreferencesStore());

      act(() => result.current.selectNoneSources(ALL_SOURCES));
      act(() => result.current.selectAllSources());

      expect(result.current.hiddenSources).toEqual([]);
      ALL_SOURCES.forEach((s) =>
        expect(result.current.isSourceVisible(s)).toBe(true),
      );
    });
  });

  describe('persisted-state migration', () => {
    it('derives the lens from legacy booleans without crashing', () => {
      // Simulate the migrate() body against pre-v1 persisted shapes.
      const migrate = (persisted: any, version: number) => {
        if (!persisted) return persisted;
        if (version < 1 && persisted.groupByDimension === undefined) {
          // Legacy groupBySource was source_context grouping -> maps to 'scheme'
          // ('source' now means the originating file).
          persisted.groupByDimension = persisted.groupBySource
            ? 'scheme'
            : persisted.groupByDomain
              ? 'domain'
              : 'none';
        }
        if (persisted.groupByFile === undefined) {
          persisted.groupByFile = persisted.groupByDimension === 'source';
        }
        return persisted;
      };

      expect(migrate({ groupBySource: true, groupByDomain: false }, 0).groupByDimension).toBe('scheme');
      expect(migrate({ groupBySource: false, groupByDomain: true }, 0).groupByDimension).toBe('domain');
      expect(migrate({ groupBySource: false, groupByDomain: false }, 0).groupByDimension).toBe('none');
      // 'source' dimension back-fills groupByFile.
      expect(migrate({ groupByDimension: 'source' }, 1).groupByFile).toBe(true);
      expect(migrate({ groupByDimension: 'scheme' }, 1).groupByFile).toBe(false);
      // No persisted state and already-migrated state are both handled safely.
      expect(migrate(undefined, 0)).toBeUndefined();
      expect(migrate({ groupByDimension: 'scheme' }, 1).groupByDimension).toBe('scheme');
    });
  });

  describe('conceptListSearch is session-only', () => {
    const options = useGlossaryPreferencesStore.persist.getOptions();

    it('is not included in the persisted slice', () => {
      act(() => useGlossaryPreferencesStore.getState().setConceptListSearch('Assetype'));
      const persisted = options.partialize!(useGlossaryPreferencesStore.getState()) as Record<string, unknown>;
      expect(persisted).not.toHaveProperty('conceptListSearch');
      // Still kept in memory for in-app navigation.
      expect(useGlossaryPreferencesStore.getState().conceptListSearch).toBe('Assetype');
    });

    it('bumps the persist version and clears a stale stored search on migrate', () => {
      expect(options.version).toBe(3);
      const migrated = options.migrate!(
        { groupByDimension: 'scheme', groupByFile: false, conceptListSearch: 'Assetype' },
        1,
      ) as Record<string, unknown>;
      expect(migrated).not.toHaveProperty('conceptListSearch');
      expect(migrated.groupByDimension).toBe('scheme');
    });
  });

  describe('persisted UI options (sort mode + Graph tab)', () => {
    const options = useGlossaryPreferencesStore.persist.getOptions();

    it('defaults sort to Name and graph options to the previous hard-coded values', () => {
      const s = useGlossaryPreferencesStore.getState();
      expect(s.sourceSortMode).toBe('name');
      expect(s.graphLayout).toBe('cose');
      expect(s.graphShowDomainBoxes).toBe(true);
      expect(s.graphShowNodeLabels).toBe(false);
      expect(s.graphShowEdgeLabels).toBe(false);
      expect(s.graphNodeSize).toBe(24);
      expect(s.graphSpacing).toBe(80);
    });

    it('includes the sort mode and graph options in the persisted slice', () => {
      act(() => {
        const s = useGlossaryPreferencesStore.getState();
        s.setSourceSortMode('size');
        s.setGraphOption('graphLayout', 'grid');
        s.setGraphOption('graphShowNodeLabels', (prev) => !prev);
        s.setGraphOption('graphShowDomainBoxes', false);
        s.setGraphOption('graphNodeSize', 40);
        s.setGraphOption('graphSpacing', 120);
      });
      const persisted = options.partialize!(useGlossaryPreferencesStore.getState()) as Record<string, unknown>;
      expect(persisted).toMatchObject({
        sourceSortMode: 'size',
        graphLayout: 'grid',
        graphShowNodeLabels: true,
        graphShowEdgeLabels: false,
        graphShowDomainBoxes: false,
        graphNodeSize: 40,
        graphSpacing: 120,
      });
      // Session-only fields remain excluded.
      expect(persisted).not.toHaveProperty('conceptListSearch');
      expect(persisted).not.toHaveProperty('conceptListScrollTop');
    });

    it('back-fills defaults when migrating a v2 state and keeps existing fields', () => {
      const migrated = options.migrate!(
        { groupByDimension: 'domain', groupByFile: false, sourceSortMode: 'bogus', graphNodeSize: 'x' },
        2,
      ) as Record<string, unknown>;
      expect(migrated.groupByDimension).toBe('domain');
      expect(migrated.sourceSortMode).toBe('name');
      expect(migrated.graphNodeSize).toBe(24);
      expect(migrated.graphLayout).toBe('cose');
      expect(migrated.graphShowDomainBoxes).toBe(true);
    });

    it('preserves valid v2-era values on migrate', () => {
      const migrated = options.migrate!(
        { groupByDimension: 'none', sourceSortMode: 'size', graphSpacing: 150 },
        2,
      ) as Record<string, unknown>;
      expect(migrated.sourceSortMode).toBe('size');
      expect(migrated.graphSpacing).toBe(150);
    });
  });
});
