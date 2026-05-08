import { describe, it, expect } from 'vitest';
import {
  ALL_TRIGGER_TYPES,
  ALL_ENTITY_TYPES,
  SUPPORTED_TRIGGER_ENTITY_MAP,
  isTriggerEntitySupported,
} from './workflow-labels';

describe('workflow-labels', () => {
  describe('ALL_TRIGGER_TYPES', () => {
    it('includes on_first_access (frontend/backend type sync)', () => {
      expect(ALL_TRIGGER_TYPES).toContain('on_first_access');
    });

    it('has no duplicate trigger types', () => {
      const set = new Set(ALL_TRIGGER_TYPES);
      expect(set.size).toBe(ALL_TRIGGER_TYPES.length);
    });
  });

  describe('ALL_ENTITY_TYPES', () => {
    it('includes user (frontend/backend type sync)', () => {
      expect(ALL_ENTITY_TYPES).toContain('user');
    });

    it('has no duplicate entity types', () => {
      const set = new Set(ALL_ENTITY_TYPES);
      expect(set.size).toBe(ALL_ENTITY_TYPES.length);
    });
  });

  describe('SUPPORTED_TRIGGER_ENTITY_MAP', () => {
    it('maps on_first_access to user entity', () => {
      expect(SUPPORTED_TRIGGER_ENTITY_MAP.on_first_access).toEqual(['user']);
    });

    it('reports on_first_access + user as supported', () => {
      expect(isTriggerEntitySupported('on_first_access', 'user')).toBe(true);
    });

    it('reports on_first_access + table as unsupported', () => {
      expect(isTriggerEntitySupported('on_first_access', 'table')).toBe(false);
    });
  });
});
