import { describe, it, expect } from 'vitest';
import {
  DataContractStatus,
  ALLOWED_TRANSITIONS,
  STATUS_CONFIG,
  canTransitionTo,
  getAllowedTransitions,
  getStatusConfig,
  validateTransition,
  getRecommendedAction,
} from './odcs-lifecycle';

describe('odcs-lifecycle', () => {
  describe('canTransitionTo', () => {
    it('allows defined transitions', () => {
      expect(canTransitionTo(DataContractStatus.DRAFT, DataContractStatus.PROPOSED)).toBe(true);
      expect(canTransitionTo(DataContractStatus.APPROVED, DataContractStatus.ACTIVE)).toBe(true);
      expect(canTransitionTo(DataContractStatus.DEPRECATED, DataContractStatus.ACTIVE)).toBe(true);
    });

    it('rejects undefined transitions and same-status', () => {
      expect(canTransitionTo(DataContractStatus.DRAFT, DataContractStatus.ACTIVE)).toBe(false);
      expect(canTransitionTo(DataContractStatus.ACTIVE, DataContractStatus.ACTIVE)).toBe(false);
      expect(canTransitionTo(DataContractStatus.RETIRED, DataContractStatus.DRAFT)).toBe(false);
    });

    it('is case-insensitive', () => {
      expect(canTransitionTo('Draft', 'PROPOSED')).toBe(true);
    });
  });

  describe('getAllowedTransitions', () => {
    it('mirrors the transition table', () => {
      expect(getAllowedTransitions(DataContractStatus.PROPOSED)).toEqual(
        ALLOWED_TRANSITIONS[DataContractStatus.PROPOSED],
      );
    });

    it('returns [] for terminal and unknown statuses', () => {
      expect(getAllowedTransitions(DataContractStatus.RETIRED)).toEqual([]);
      expect(getAllowedTransitions('bogus')).toEqual([]);
    });
  });

  describe('getStatusConfig', () => {
    it('returns config for a known status', () => {
      expect(getStatusConfig(DataContractStatus.DRAFT)).toEqual(
        STATUS_CONFIG[DataContractStatus.DRAFT],
      );
    });

    it('falls back for an unknown status', () => {
      const cfg = getStatusConfig('xyz');
      expect(cfg).toMatchObject({ label: 'xyz', description: 'Unknown status', variant: 'secondary' });
    });
  });

  describe('validateTransition', () => {
    it('accepts a valid transition', () => {
      expect(validateTransition(DataContractStatus.DRAFT, DataContractStatus.PROPOSED)).toEqual({
        valid: true,
      });
    });

    it('rejects unknown target', () => {
      const r = validateTransition(DataContractStatus.DRAFT, 'invalid');
      expect(r.valid).toBe(false);
      expect(r.error).toContain('Invalid target status');
    });

    it('rejects same status with contract-specific message', () => {
      const r = validateTransition(DataContractStatus.ACTIVE, DataContractStatus.ACTIVE);
      expect(r.valid).toBe(false);
      expect(r.error).toBe('Contract is already in this status');
    });

    it('rejects disallowed transition and reports "none" for terminal', () => {
      const r = validateTransition(DataContractStatus.RETIRED, DataContractStatus.DRAFT);
      expect(r.valid).toBe(false);
      expect(r.error).toContain('none');
    });

    it('lists allowed labels for a non-terminal disallowed transition', () => {
      const r = validateTransition(DataContractStatus.DRAFT, DataContractStatus.ACTIVE);
      expect(r.valid).toBe(false);
      expect(r.error).toContain('Cannot transition');
      expect(r.error).not.toContain('none');
    });
  });

  describe('getRecommendedAction', () => {
    it('returns guidance for non-terminal statuses', () => {
      for (const s of [
        DataContractStatus.DRAFT,
        DataContractStatus.PROPOSED,
        DataContractStatus.UNDER_REVIEW,
        DataContractStatus.APPROVED,
        DataContractStatus.ACTIVE,
        DataContractStatus.DEPRECATED,
      ]) {
        expect(getRecommendedAction(s)).toBeTruthy();
      }
    });

    it('returns null for retired and unknown', () => {
      expect(getRecommendedAction(DataContractStatus.RETIRED)).toBeNull();
      expect(getRecommendedAction('unknown')).toBeNull();
    });
  });
});
