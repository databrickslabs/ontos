/**
 * Tests for the OutputPort → Asset predicate map exported from
 * `data-product-details.tsx`.
 *
 * The component file itself pulls in many heavy modules; we deliberately keep
 * these tests at the constant/lookup level to avoid importing the full view.
 * The map is the contract that has to stay in lock-step with the ontology
 * (`portHas*` predicates in `ontos-ontology.ttl`).
 */
import { describe, it, expect } from 'vitest';
import { PORT_TO_ASSET_PREDICATE } from './data-product-details';

describe('PORT_TO_ASSET_PREDICATE', () => {
  it('maps each deliverable asset type to its ontology predicate', () => {
    expect(PORT_TO_ASSET_PREDICATE).toEqual({
      Table: 'portHasTable',
      View: 'portHasView',
      Dataset: 'portHasDataset',
      APIEndpoint: 'portHasEndpoint',
      MLModel: 'portHasModel',
    });
  });

  it('returns undefined for container types the ontology rejects', () => {
    // Catalog/Schema were the original 422 trigger — they must not have an
    // entry. If someone adds them here, the corresponding TTL predicate must
    // also exist.
    expect(PORT_TO_ASSET_PREDICATE['Catalog' as keyof typeof PORT_TO_ASSET_PREDICATE]).toBeUndefined();
    expect(PORT_TO_ASSET_PREDICATE['Schema' as keyof typeof PORT_TO_ASSET_PREDICATE]).toBeUndefined();
  });

  it('returns undefined for unknown types so callers can skip + warn', () => {
    expect(PORT_TO_ASSET_PREDICATE['Notebook' as keyof typeof PORT_TO_ASSET_PREDICATE]).toBeUndefined();
    expect(PORT_TO_ASSET_PREDICATE['Dashboard' as keyof typeof PORT_TO_ASSET_PREDICATE]).toBeUndefined();
  });
});

/**
 * Predicate-selection behaviour expected of `handleLinkAssets`. We test the
 * pure logic (compute predicate from asset type) here; the wired-in fetch is
 * verified end-to-end against the deployed app.
 */
describe('predicate selection (mirrors handleLinkAssets)', () => {
  const pickPredicate = (assetType: string | undefined): string | undefined =>
    assetType ? PORT_TO_ASSET_PREDICATE[assetType as keyof typeof PORT_TO_ASSET_PREDICATE] : undefined;

  it.each([
    ['Table', 'portHasTable'],
    ['View', 'portHasView'],
    ['Dataset', 'portHasDataset'],
    ['APIEndpoint', 'portHasEndpoint'],
    ['MLModel', 'portHasModel'],
  ])('picks %s → %s', (assetType, predicate) => {
    expect(pickPredicate(assetType)).toBe(predicate);
  });

  it('returns undefined for Catalog/Schema (the original 422 trigger)', () => {
    expect(pickPredicate('Catalog')).toBeUndefined();
    expect(pickPredicate('Schema')).toBeUndefined();
  });

  it('returns undefined when asset_type_name is missing', () => {
    expect(pickPredicate(undefined)).toBeUndefined();
  });
});
