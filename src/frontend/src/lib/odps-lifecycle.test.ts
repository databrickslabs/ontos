import { describe, it, expect } from 'vitest';
import { DataProductStatus } from '@/types/data-product';
import {
  ALLOWED_TRANSITIONS,
  STATUS_CONFIG,
  canTransitionTo,
  getAllowedTransitions,
  getStatusConfig,
  validateTransition,
  getRecommendedAction,
} from './odps-lifecycle';

describe('odps-lifecycle', () => {
  describe('canTransitionTo', () => {
    it('allows a defined forward transition', () => {
      expect(canTransitionTo(DataProductStatus.DRAFT, DataProductStatus.PROPOSED)).toBe(true);
      expect(canTransitionTo(DataProductStatus.APPROVED, DataProductStatus.ACTIVE)).toBe(true);
    });

    it('rejects an undefined transition', () => {
      expect(canTransitionTo(DataProductStatus.DRAFT, DataProductStatus.ACTIVE)).toBe(false);
      expect(canTransitionTo(DataProductStatus.RETIRED, DataProductStatus.ACTIVE)).toBe(false);
    });

    it('rejects a no-op transition to the same status', () => {
      expect(canTransitionTo(DataProductStatus.ACTIVE, DataProductStatus.ACTIVE)).toBe(false);
    });

    it('is case-insensitive', () => {
      expect(canTransitionTo('DRAFT', 'Proposed')).toBe(true);
    });

    it('allows emergency deprecation from draft', () => {
      expect(canTransitionTo(DataProductStatus.DRAFT, DataProductStatus.DEPRECATED)).toBe(true);
    });
  });

  describe('getAllowedTransitions', () => {
    it('returns the configured targets for a known status', () => {
      expect(getAllowedTransitions(DataProductStatus.ACTIVE)).toEqual(
        ALLOWED_TRANSITIONS[DataProductStatus.ACTIVE],
      );
    });

    it('returns an empty array for a terminal status', () => {
      expect(getAllowedTransitions(DataProductStatus.RETIRED)).toEqual([]);
    });

    it('returns an empty array for an unknown status', () => {
      expect(getAllowedTransitions('does-not-exist')).toEqual([]);
    });
  });

  describe('getStatusConfig', () => {
    it('returns the configured entry for a known status', () => {
      expect(getStatusConfig(DataProductStatus.ACTIVE)).toEqual(
        STATUS_CONFIG[DataProductStatus.ACTIVE],
      );
    });

    it('falls back to a secondary config for an unknown status', () => {
      const cfg = getStatusConfig('mystery');
      expect(cfg.label).toBe('mystery');
      expect(cfg.description).toBe('Unknown status');
      expect(cfg.variant).toBe('secondary');
    });
  });

  describe('validateTransition', () => {
    it('accepts a valid transition', () => {
      expect(validateTransition(DataProductStatus.DRAFT, DataProductStatus.PROPOSED)).toEqual({
        valid: true,
      });
    });

    it('rejects an unknown target status', () => {
      const result = validateTransition(DataProductStatus.DRAFT, 'nonsense');
      expect(result.valid).toBe(false);
      expect(result.error).toContain('Invalid target status');
    });

    it('rejects a same-status transition', () => {
      const result = validateTransition(DataProductStatus.ACTIVE, DataProductStatus.ACTIVE);
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Product is already in this status');
    });

    it('rejects a disallowed transition and lists allowed targets', () => {
      const result = validateTransition(DataProductStatus.RETIRED, DataProductStatus.ACTIVE);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('Cannot transition');
      expect(result.error).toContain('none');
    });
  });

  describe('getRecommendedAction', () => {
    it('returns guidance for each non-terminal status', () => {
      for (const status of [
        DataProductStatus.DRAFT,
        DataProductStatus.SANDBOX,
        DataProductStatus.PROPOSED,
        DataProductStatus.UNDER_REVIEW,
        DataProductStatus.APPROVED,
        DataProductStatus.ACTIVE,
        DataProductStatus.DEPRECATED,
      ]) {
        expect(getRecommendedAction(status)).toBeTruthy();
      }
    });

    it('returns null for the terminal retired status', () => {
      expect(getRecommendedAction(DataProductStatus.RETIRED)).toBeNull();
    });

    it('returns null for an unknown status', () => {
      expect(getRecommendedAction('whatever')).toBeNull();
    });
  });
});
