import { describe, it, expect } from 'vitest';
import {
  features,
  getFeatureByPath,
  getFeatureNameByPath,
  getNavigationGroups,
  getLandingPageFeatures,
  getNavFeatureId,
  isHiddenInNav,
  NAV_ENTRY_FEATURES,
} from './features';

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

    it('leaves out the features hidden from navigation (#1325)', () => {
      const ids = (hidden: string[]) => getLandingPageFeatures(['ga'], hidden).map((f) => f.id);
      expect(ids([])).toEqual(expect.arrayContaining(['data-contracts', 'concepts']));
      // concepts is gated by the semantic-models role feature.
      expect(ids(['data-contracts', 'semantic-models'])).not.toEqual(
        expect.arrayContaining(['data-contracts']),
      );
      expect(ids(['data-contracts', 'semantic-models'])).not.toContain('concepts');
    });
  });

  describe('hidden navigation features (#1325)', () => {
    const navIds = (hidden: ReadonlySet<string> | string[]) =>
      getNavigationGroups(['ga', 'beta', 'alpha'], hidden).flatMap((g) => g.items.map((i) => i.id));

    it('uses the permission id of an entry as its role feature id', () => {
      const concepts = features.find((f) => f.id === 'concepts')!;
      expect(getNavFeatureId(concepts)).toBe('semantic-models');
      expect(isHiddenInNav(concepts, ['semantic-models'])).toBe(true);
    });

    it('gives Marketplace and My Products their own flag, apart from Products', () => {
      const marketplace = features.find((f) => f.id === 'marketplace')!;
      const myProducts = features.find((f) => f.id === 'my-products')!;
      const products = features.find((f) => f.id === 'data-products')!;
      expect(getNavFeatureId(marketplace)).toBe('marketplace');
      expect(getNavFeatureId(myProducts)).toBe('my-products');
      expect(getNavFeatureId(products)).toBe('data-products');
      // Access checks still follow the Products permission.
      expect(marketplace.permissionId).toBe('data-products');
      expect(myProducts.permissionId).toBe('data-products');
      expect(NAV_ENTRY_FEATURES).toEqual({
        marketplace: 'data-products', 'my-products': 'data-products',
      });

      expect(isHiddenInNav(marketplace, ['data-products'])).toBe(false);
      expect(isHiddenInNav(products, ['marketplace', 'my-products'])).toBe(false);
      expect(isHiddenInNav(marketplace, new Set(['marketplace']))).toBe(true);
      expect(isHiddenInNav(myProducts, new Set(['my-products']))).toBe(true);
    });

    it('lists My Products in the Build group unless it is hidden', () => {
      expect(navIds([])).toContain('my-products');
      expect(navIds(['my-products'])).not.toContain('my-products');
      expect(navIds(['my-products'])).toContain('data-products');
    });

    it('drops hidden entries from the groups, from an array or a set', () => {
      expect(navIds([])).toContain('data-contracts');
      for (const hidden of [['data-contracts', 'assets'], new Set(['data-contracts', 'assets'])]) {
        const ids = navIds(hidden);
        expect(ids).not.toContain('data-contracts');
        expect(ids).not.toContain('assets');
        expect(ids).toContain('data-catalog');
      }
    });
  });
});
