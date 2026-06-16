import { describe, it, expect } from 'vitest';
import { UCAssetType } from '@/types/uc-asset';
import {
  parseSearchQuery,
  matchesSegment,
  findFirstMatch,
  filterBySegment,
  getTypeFilterDisplayName,
  buildPathToLevel,
  getNavigationLevel,
  getCurrentLevelFilter,
  isTypeAllowed,
} from './uc-search-parser';

describe('uc-search-parser', () => {
  describe('parseSearchQuery', () => {
    it('parses a plain dotted path into segments', () => {
      const r = parseSearchQuery('lars.te.taa');
      expect(r.typeFilter).toBeNull();
      expect(r.segments).toEqual(['lars', 'te', 'taa']);
      expect(r.endsWithDot).toBe(false);
      expect(r.rawQuery).toBe('lars.te.taa');
    });

    it('extracts a type prefix', () => {
      const r = parseSearchQuery('t:main.def');
      expect(r.typeFilter).toBe(UCAssetType.TABLE);
      expect(r.pathQuery).toBe('main.def');
      expect(r.segments).toEqual(['main', 'def']);
    });

    it('detects a trailing dot as expansion intent', () => {
      const r = parseSearchQuery('main.');
      expect(r.endsWithDot).toBe(true);
      expect(r.segments).toEqual(['main']);
    });

    it('ignores an unknown prefix and treats the colon text as path', () => {
      const r = parseSearchQuery('zzz:foo');
      expect(r.typeFilter).toBeNull();
      // No known prefix matched, so the whole string stays as the path query.
      expect(r.pathQuery).toBe('zzz:foo');
    });

    it('handles a bare type prefix with no path', () => {
      const r = parseSearchQuery('v:');
      expect(r.typeFilter).toBe(UCAssetType.VIEW);
      expect(r.segments).toEqual([]);
    });
  });

  describe('matchesSegment', () => {
    it('matches prefixes case-insensitively', () => {
      expect(matchesSegment('Lars_George', 'lars')).toBe(true);
      expect(matchesSegment('orders', 'ord')).toBe(true);
    });

    it('does not match a non-prefix', () => {
      expect(matchesSegment('orders', 'xyz')).toBe(false);
    });

    it('matches everything for an empty segment', () => {
      expect(matchesSegment('anything', '')).toBe(true);
    });
  });

  describe('findFirstMatch / filterBySegment', () => {
    const items = [{ name: 'alpha' }, { name: 'apple' }, { name: 'beta' }];

    it('finds the first matching item', () => {
      expect(findFirstMatch(items, 'a')?.name).toBe('alpha');
      expect(findFirstMatch(items, 'be')?.name).toBe('beta');
    });

    it('returns the first item when the segment is empty', () => {
      expect(findFirstMatch(items, '')?.name).toBe('alpha');
    });

    it('filters items by segment', () => {
      expect(filterBySegment(items, 'a').map((i) => i.name)).toEqual(['alpha', 'apple']);
      expect(filterBySegment(items, '')).toEqual(items);
    });
  });

  describe('getTypeFilterDisplayName', () => {
    it('returns "All types" for null', () => {
      expect(getTypeFilterDisplayName(null)).toBe('All types');
    });

    it('returns readable names per type', () => {
      expect(getTypeFilterDisplayName(UCAssetType.TABLE)).toBe('Tables');
      expect(getTypeFilterDisplayName(UCAssetType.MATERIALIZED_VIEW)).toBe('Materialized Views');
      expect(getTypeFilterDisplayName(UCAssetType.FUNCTION)).toBe('Functions');
      expect(getTypeFilterDisplayName(UCAssetType.VOLUME)).toBe('Volumes');
      expect(getTypeFilterDisplayName(UCAssetType.METRIC)).toBe('Metrics');
    });
  });

  describe('buildPathToLevel', () => {
    it('joins segments up to the requested level', () => {
      const segs = ['a', 'b', 'c'];
      expect(buildPathToLevel(segs, 0)).toBe('a');
      expect(buildPathToLevel(segs, 1)).toBe('a.b');
      expect(buildPathToLevel(segs, 2)).toBe('a.b.c');
    });
  });

  describe('getNavigationLevel', () => {
    it('is 0 at the catalog level', () => {
      expect(getNavigationLevel(parseSearchQuery(''))).toBe(0);
    });

    it('goes one level deeper after a trailing dot (capped at 2)', () => {
      expect(getNavigationLevel(parseSearchQuery('a.'))).toBe(1);
      expect(getNavigationLevel(parseSearchQuery('a.b.c.'))).toBe(2);
    });

    it('stays at the filtering level without a trailing dot', () => {
      expect(getNavigationLevel(parseSearchQuery('a'))).toBe(0);
      expect(getNavigationLevel(parseSearchQuery('a.b'))).toBe(1);
    });
  });

  describe('getCurrentLevelFilter', () => {
    it('returns the last segment when filtering', () => {
      expect(getCurrentLevelFilter(parseSearchQuery('a.b'))).toBe('b');
    });

    it('returns empty after a trailing dot or with no segments', () => {
      expect(getCurrentLevelFilter(parseSearchQuery('a.'))).toBe('');
      expect(getCurrentLevelFilter(parseSearchQuery(''))).toBe('');
    });
  });

  describe('isTypeAllowed', () => {
    const allowed = [UCAssetType.TABLE, UCAssetType.VIEW];

    it('rejects types not in the allowed list', () => {
      expect(isTypeAllowed(UCAssetType.FUNCTION, null, allowed)).toBe(false);
    });

    it('honors an active type filter', () => {
      expect(isTypeAllowed(UCAssetType.TABLE, UCAssetType.VIEW, allowed)).toBe(false);
      expect(isTypeAllowed(UCAssetType.TABLE, UCAssetType.TABLE, allowed)).toBe(true);
    });

    it('allows any allowed type when no filter is set', () => {
      expect(isTypeAllowed(UCAssetType.VIEW, null, allowed)).toBe(true);
    });
  });
});
