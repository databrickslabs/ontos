import { describe, it, expect } from 'vitest';
import {
  getEntityDetailPathFromPayload,
  getUnderlyingEntityDetailPath,
} from './entity-detail-path';

describe('entity-detail-path', () => {
  describe('getEntityDetailPathFromPayload', () => {
    it('returns null for nullish or non-object payloads', () => {
      expect(getEntityDetailPathFromPayload(null)).toBeNull();
      expect(getEntityDetailPathFromPayload(undefined)).toBeNull();
    });

    it('resolves product ids (both key spellings)', () => {
      expect(getEntityDetailPathFromPayload({ product_id: 'p1' })).toBe('/data-products/p1');
      expect(getEntityDetailPathFromPayload({ data_product_id: 'p2' })).toBe('/data-products/p2');
    });

    it('resolves contract ids (both key spellings)', () => {
      expect(getEntityDetailPathFromPayload({ contract_id: 'c1' })).toBe('/data-contracts/c1');
      expect(getEntityDetailPathFromPayload({ data_contract_id: 'c2' })).toBe('/data-contracts/c2');
    });

    it('prefers product id over contract id', () => {
      expect(getEntityDetailPathFromPayload({ product_id: 'p', contract_id: 'c' })).toBe(
        '/data-products/p',
      );
    });

    it('resolves via entity_type + entity_id', () => {
      expect(getEntityDetailPathFromPayload({ entity_type: 'data_product', entity_id: 'e1' })).toBe(
        '/data-products/e1',
      );
      expect(
        getEntityDetailPathFromPayload({ entity_type: 'DataContract', entity_id: 'e2' }),
      ).toBe('/data-contracts/e2');
    });

    it('resolves snake_case + concept entity types', () => {
      // snake_case data_contract arm (the earlier test used the DataContract alias)
      expect(
        getEntityDetailPathFromPayload({ entity_type: 'data_contract', entity_id: 'e3' }),
      ).toBe('/data-contracts/e3');
      // ontology_concept / concept -> encoded IRI path
      expect(
        getEntityDetailPathFromPayload({
          entity_type: 'ontology_concept',
          entity_id: 'https://ontos.example.org/billing#Invoice',
        }),
      ).toBe('/concepts/browser/https%3A%2F%2Fontos.example.org%2Fbilling%23Invoice');
      expect(
        getEntityDetailPathFromPayload({ entity_type: 'concept', entity_id: 'urn:x#Y' }),
      ).toBe('/concepts/browser/urn%3Ax%23Y');
    });

    it('returns null for an unlinkable or incomplete entity', () => {
      expect(getEntityDetailPathFromPayload({ entity_type: 'access_grant', entity_id: 'g' })).toBeNull();
      expect(getEntityDetailPathFromPayload({ entity_type: 'data_product' })).toBeNull();
      expect(getEntityDetailPathFromPayload({ product_id: '' })).toBeNull();
      // non-string entity_id hits the `typeof entityId !== 'string'` guard
      expect(getEntityDetailPathFromPayload({ entity_type: 'data_product', entity_id: 123 })).toBeNull();
    });
  });

  describe('getUnderlyingEntityDetailPath', () => {
    it('resolves the underlying entity when present', () => {
      const path = getUnderlyingEntityDetailPath({
        entity_type: 'access_grant',
        entity_id: 'g1',
        underlying_entity_type: 'data_product',
        underlying_entity_id: 'u1',
      });
      expect(path).toBe('/data-products/u1');
    });

    it('falls back to the top-level payload when no underlying entity', () => {
      expect(getUnderlyingEntityDetailPath({ product_id: 'p9' })).toBe('/data-products/p9');
    });

    it('returns null for nullish payloads', () => {
      expect(getUnderlyingEntityDetailPath(null)).toBeNull();
    });
  });
});
