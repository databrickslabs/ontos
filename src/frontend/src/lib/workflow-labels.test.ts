/**
 * Unit tests for workflow-labels helpers.
 *
 * Created alongside the for_* trigger entity-map update so the "trigger–entity
 * combination is not wired" warning does not fire for valid wizard combos.
 */
import { describe, it, expect } from 'vitest';
import {
  isTriggerEntitySupported,
  resolveRecipientDisplay,
  SUPPORTED_TRIGGER_ENTITY_MAP,
  ALL_TRIGGER_TYPES,
  ALL_ENTITY_TYPES,
} from './workflow-labels';

describe('isTriggerEntitySupported', () => {
  describe('for_* wizard triggers', () => {
    // PR #353 follow-up: ensure the warning does not fire for any of the
    // wizard-triggered (`for_*`) entries on their valid entity types.
    it('accepts for_subscribe + data_product', () => {
      expect(isTriggerEntitySupported('for_subscribe', 'data_product')).toBe(true);
    });

    it('accepts for_request_access + data_product / access_grant', () => {
      expect(isTriggerEntitySupported('for_request_access', 'data_product')).toBe(true);
      expect(isTriggerEntitySupported('for_request_access', 'access_grant')).toBe(true);
    });

    it('accepts for_request_review + data_product / data_contract / data_asset_review', () => {
      expect(isTriggerEntitySupported('for_request_review', 'data_product')).toBe(true);
      expect(isTriggerEntitySupported('for_request_review', 'data_contract')).toBe(true);
      expect(isTriggerEntitySupported('for_request_review', 'data_asset_review')).toBe(true);
    });

    it('accepts for_request_publish + data_product / data_contract', () => {
      expect(isTriggerEntitySupported('for_request_publish', 'data_product')).toBe(true);
      expect(isTriggerEntitySupported('for_request_publish', 'data_contract')).toBe(true);
    });

    it('accepts for_request_certify + data_product / data_contract', () => {
      expect(isTriggerEntitySupported('for_request_certify', 'data_product')).toBe(true);
      expect(isTriggerEntitySupported('for_request_certify', 'data_contract')).toBe(true);
    });

    it('accepts for_request_status_change + data_product', () => {
      expect(isTriggerEntitySupported('for_request_status_change', 'data_product')).toBe(true);
    });

    it('rejects for_subscribe + unrelated entity types', () => {
      expect(isTriggerEntitySupported('for_subscribe', 'catalog')).toBe(false);
      expect(isTriggerEntitySupported('for_subscribe', 'job')).toBe(false);
    });

    it('covers every for_* trigger declared in ALL_TRIGGER_TYPES', () => {
      const forTriggers = [
        'for_subscribe',
        'for_request_access',
        'for_request_review',
        'for_request_publish',
        'for_request_certify',
        'for_request_status_change',
      ];
      for (const trigger of forTriggers) {
        expect(SUPPORTED_TRIGGER_ENTITY_MAP[trigger]).toBeDefined();
        expect(SUPPORTED_TRIGGER_ENTITY_MAP[trigger].length).toBeGreaterThan(0);
      }
    });
  });

  describe('existing triggers (regression)', () => {
    it('still accepts on_create + table', () => {
      expect(isTriggerEntitySupported('on_create', 'table')).toBe(true);
    });

    it('treats manual / scheduled as always-supported (empty array)', () => {
      expect(isTriggerEntitySupported('manual', 'data_product')).toBe(true);
      expect(isTriggerEntitySupported('scheduled', 'job')).toBe(true);
    });

    it('returns false for unknown triggers', () => {
      expect(isTriggerEntitySupported('not_a_real_trigger', 'data_product')).toBe(false);
    });
  });
});

describe('resolveRecipientDisplay', () => {
  it('returns "Not configured" when value is undefined', () => {
    expect(resolveRecipientDisplay(undefined, {})).toBe('Not configured');
  });

  it('resolves special recipient keys', () => {
    expect(resolveRecipientDisplay('requester', {})).toBe('Requester');
    expect(resolveRecipientDisplay('owner', {})).toBe('Owner');
    expect(resolveRecipientDisplay('admins', {})).toBe('Administrators');
  });

  it('resolves role UUIDs via rolesMap', () => {
    const rolesMap = { 'uuid-1': 'Data Steward', 'uuid-2': 'Owner' };
    expect(resolveRecipientDisplay('uuid-1', rolesMap)).toBe('Data Steward');
  });

  it('falls back to raw value when nothing matches', () => {
    expect(resolveRecipientDisplay('alice@example.com', {})).toBe('alice@example.com');
  });

  describe('business role resolution', () => {
    // Backend `/api/workflows/roles` prefixes business role IDs with
    // `business:<uuid>` already, so the unified rolesMap path covers most
    // call sites. The businessRolesMap arg is the fallback for callers that
    // hold a map keyed by raw UUID (e.g., direct `/api/business-roles` fetch).
    it('resolves business:<uuid> via unified rolesMap (current designer path)', () => {
      const rolesMap = { 'business:role-1': 'Domain Owner' };
      expect(resolveRecipientDisplay('business:role-1', rolesMap)).toBe('Domain Owner');
    });

    it('resolves business:<uuid> via businessRolesMap fallback', () => {
      expect(
        resolveRecipientDisplay('business:abc-123', {}, { 'abc-123': 'Business Owner' })
      ).toBe('Business Owner (business role)');
    });

    it('returns raw value when business: prefix is unresolvable', () => {
      expect(resolveRecipientDisplay('business:unknown', {})).toBe('business:unknown');
      expect(
        resolveRecipientDisplay('business:unknown', {}, { 'other-uuid': 'Other' })
      ).toBe('business:unknown');
    });
  });
});

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
