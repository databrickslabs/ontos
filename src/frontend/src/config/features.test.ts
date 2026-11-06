import { describe, it, expect } from 'vitest';
import {
  features,
  getFeatureByPath,
  getFeatureNameByPath,
  getNavigationGroups,
  getLandingPageFeatures,
  EDITIONS,
  type FeatureMaturity,
} from './features';

const ESSENTIALS = [
  'search', 'data-catalog', 'assets', 'concepts', 'data-asset-reviews', 'my-requests',
];
const MATURITY_SETS: FeatureMaturity[][] = [['ga'], ['ga', 'beta'], ['ga', 'beta', 'alpha']];
const navIds = (groups: ReturnType<typeof getNavigationGroups>) =>
  groups.flatMap((g) => g.items.map((i) => i.id));

describe('features config', () => {
  it('defines a non-empty, well-formed feature catalog', () => {
    expect(features.length).toBeGreaterThan(0);
    for (const f of features) {
      expect(f.id).toBeTruthy();
      expect(f.name).toBeTruthy();
      expect(f.path.startsWith('/')).toBe(true);
      expect(['Discover', 'Build', 'Govern', 'Deploy']).toContain(f.group);
      expect(['ga', 'beta', 'alpha']).toContain(f.maturity);
    }
  });

  it('has unique feature ids and paths', () => {
    expect(new Set(features.map((f) => f.id)).size).toBe(features.length);
    expect(new Set(features.map((f) => f.path)).size).toBe(features.length);
  });

  describe('getFeatureByPath', () => {
    it('finds a feature by its exact path', () => {
      const first = features[0];
      expect(getFeatureByPath(first.path)).toEqual(first);
    });

    it('returns undefined for an unknown path', () => {
      expect(getFeatureByPath('/definitely-not-a-feature')).toBeUndefined();
    });
  });

  describe('getFeatureNameByPath', () => {
    it('resolves a name from a leading-slash or bare path segment', () => {
      const first = features[0];
      const segment = first.path.replace(/^\//, '');
      expect(getFeatureNameByPath(segment)).toBe(first.name);
      expect(getFeatureNameByPath(first.path)).toBe(first.name);
    });

    it('echoes the segment when no feature matches', () => {
      expect(getFeatureNameByPath('unknown-segment')).toBe('unknown-segment');
    });
  });

  describe('getNavigationGroups', () => {
    it('groups GA features in canonical group order with no empty groups', () => {
      const groups = getNavigationGroups(['ga']);
      const order = ['Discover', 'Build', 'Govern', 'Deploy'];
      const seen: string[] = groups.map((g) => g.name);
      // Names appear in the canonical relative order.
      expect(seen).toEqual([...order].filter((n) => seen.includes(n)));
      for (const g of groups) {
        expect(g.items.length).toBeGreaterThan(0);
        expect(g.items.every((i) => i.maturity === 'ga')).toBe(true);
      }
    });

    it('widens results when more maturities are allowed', () => {
      const ga = getNavigationGroups(['ga']).reduce((n, g) => n + g.items.length, 0);
      const all = getNavigationGroups(['ga', 'beta', 'alpha']).reduce(
        (n, g) => n + g.items.length,
        0,
      );
      expect(all).toBeGreaterThanOrEqual(ga);
    });
  });

  describe('getLandingPageFeatures', () => {
    it('returns only landing GA features', () => {
      const landing = getLandingPageFeatures(['ga']);
      expect(landing.every((f) => f.showInLanding && f.maturity === 'ga')).toBe(true);
    });
  });

  describe('editions', () => {
    it('every feature declares at least one known edition, and all are in Full', () => {
      for (const f of features) {
        expect(Array.isArray(f.editions), f.id).toBe(true);
        expect(f.editions.length, f.id).toBeGreaterThan(0);
        expect(f.editions.every((e) => EDITIONS.includes(e)), f.id).toBe(true);
        expect(f.editions, f.id).toContain('full');
      }
    });

    it('Essentials is exactly the curated set', () => {
      const ids = features.filter((f) => f.editions.includes('essentials')).map((f) => f.id);
      expect(ids.sort()).toEqual([...ESSENTIALS].sort());
    });

    it.each(MATURITY_SETS)('navigation: Full keeps every feature of maturity %s', (...m) => {
      const expected = features.filter((f) => m.includes(f.maturity)).map((f) => f.id);
      expect(navIds(getNavigationGroups(m, 'full')).sort()).toEqual(expected.sort());
      // The edition defaults to Full, so the old call signature is unchanged.
      expect(navIds(getNavigationGroups(m))).toEqual(navIds(getNavigationGroups(m, 'full')));
    });

    it.each(MATURITY_SETS)('navigation: Essentials applies both filters for %s', (...m) => {
      const expected = features
        .filter((f) => ESSENTIALS.includes(f.id) && m.includes(f.maturity))
        .map((f) => f.id);
      expect(navIds(getNavigationGroups(m, 'essentials')).sort()).toEqual(expected.sort());
    });

    it('navigation: Essentials shows the six with beta, loses reviews without it', () => {
      expect(navIds(getNavigationGroups(['ga', 'beta'], 'essentials')).sort())
        .toEqual([...ESSENTIALS].sort());
      expect(navIds(getNavigationGroups(['ga'], 'essentials'))).not.toContain(
        'data-asset-reviews',
      );
    });

    it.each(MATURITY_SETS)('landing: both filters apply per edition for %s', (...m) => {
      for (const edition of EDITIONS) {
        const expected = features
          .filter((f) => f.showInLanding && m.includes(f.maturity))
          .filter((f) => f.editions.includes(edition))
          .map((f) => f.id);
        expect(getLandingPageFeatures(m, edition).map((f) => f.id)).toEqual(expected);
      }
      expect(getLandingPageFeatures(m)).toEqual(getLandingPageFeatures(m, 'full'));
    });

    it('landing: Essentials hides products, contracts and compliance', () => {
      const ids = getLandingPageFeatures(['ga', 'beta', 'alpha'], 'essentials').map((f) => f.id);
      expect(ids).toEqual(expect.arrayContaining(['data-catalog', 'assets', 'concepts']));
      for (const hidden of ['data-products', 'data-contracts', 'compliance', 'estate-manager']) {
        expect(ids).not.toContain(hidden);
      }
    });
  });
});
