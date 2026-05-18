/**
 * Unit tests for workflow-labels helpers.
 *
 * Covers:
 *   - isTriggerEntitySupported + SUPPORTED_TRIGGER_ENTITY_MAP (PR #353 wizard wiring)
 *   - resolveRecipientDisplay (workflow recipient resolver)
 *   - ALL_TRIGGER_TYPES / ALL_ENTITY_TYPES sync invariants
 *   - getTriggerLabel + TRIGGER_LABELS (user-approved canonical labels)
 */
import { describe, it, expect } from 'vitest';
import {
  isTriggerEntitySupported,
  resolveRecipientDisplay,
  SUPPORTED_TRIGGER_ENTITY_MAP,
  ALL_TRIGGER_TYPES,
  ALL_ENTITY_TYPES,
  getTriggerLabel,
  TRIGGER_LABELS,
  TRIGGER_REQUIRED_PERMISSION,
  getRequiredPermission,
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

describe('getTriggerLabel', () => {
  // (value, expected) — one row per TriggerType, matching the backend
  // _TRIGGER_LABELS dict and the user-approved table in the PR brief.
  const expected: Array<[string, string]> = [
    ['for_subscribe', 'When a user subscribes'],
    ['on_subscribe', 'After a subscription is created'],
    ['for_request_access', 'When a user requests access'],
    ['on_request_access', 'After an access request is submitted'],
    ['for_request_review', 'When a user requests review'],
    ['on_request_review', 'After a review request is submitted'],
    ['for_request_publish', 'When a user requests publish'],
    ['on_request_publish', 'After a publish request is submitted'],
    ['for_request_certify', 'When a user requests certification'],
    ['on_request_certify', 'After a certification request is submitted'],
    ['for_request_status_change', 'When a user requests status change'],
    ['on_request_status_change', 'After a status change request is submitted'],
    ['for_approval_response', 'Approval response dialog'],
    ['before_create', 'Before entity is created (validation)'],
    ['before_update', 'Before entity is updated (validation)'],
    ['before_status_change', 'Before status changes (validation)'],
    ['on_create', 'After entity is created'],
    ['on_update', 'After entity is updated'],
    ['on_delete', 'After entity is deleted'],
    ['on_status_change', 'After status changes'],
    ['on_publish', 'After entity is published'],
    ['on_unpublish', 'After entity is unpublished'],
    ['on_revoke', 'After access is revoked'],
    ['on_expiring', 'When access is about to expire'],
    ['on_first_access', 'First time a user accesses (consent)'],
    ['on_unsubscribe', 'After a user unsubscribes'],
    ['on_job_success', 'After a background job succeeds'],
    ['on_job_failure', 'After a background job fails'],
    ['scheduled', 'On a schedule (cron)'],
    ['manual', 'Manually triggered'],
    ['on_certify', 'After entity is certified'],
    ['on_decertify', 'After entity is decertified'],
  ];

  it.each(expected)('returns canonical label for %s', (value, label) => {
    expect(getTriggerLabel(value)).toBe(label);
  });

  it('falls back to title-cased value for unknown triggers', () => {
    // Forward-compat: if a new trigger is added to the enum before the
    // table is updated, we should still render something reasonable.
    expect(getTriggerLabel('on_brand_new_event')).toBe('On Brand New Event');
  });

  it('every value in ALL_TRIGGER_TYPES has a canonical label', () => {
    for (const value of ALL_TRIGGER_TYPES) {
      expect(TRIGGER_LABELS[value]).toBeTruthy();
    }
  });
});

describe('TRIGGER_REQUIRED_PERMISSION + getRequiredPermission', () => {
  // Pin each row of the dispatch mirror so any drift from the backend
  // table is caught by tests. Keep in sync with WIZARD_PERMISSION_DISPATCH
  // in src/backend/src/routes/workflows_routes.py.
  const expected: Array<[string, { feature: string; level: string } | null]> = [
    ['for_request_access',        { feature: 'access-grants',  level: 'Read-only' }],
    ['for_subscribe',             { feature: 'data-products',  level: 'Read-only' }],
    ['for_request_review',        { feature: 'data-contracts', level: 'Read-only' }],
    ['for_request_publish',       { feature: 'data-products',  level: 'Read/Write' }],
    ['for_request_certify',       { feature: 'data-contracts', level: 'Read/Write' }],
    ['for_request_status_change', { feature: 'data-products',  level: 'Read/Write' }],
    ['on_first_access',           null],
    ['for_approval_response',     { feature: 'settings',       level: 'Read-only' }],
  ];

  it.each(expected)('TRIGGER_REQUIRED_PERMISSION[%s] matches expected', (trigger, value) => {
    expect(TRIGGER_REQUIRED_PERMISSION[trigger]).toEqual(value);
  });

  it.each(expected)('getRequiredPermission(%s) returns the dispatch row', (trigger, value) => {
    expect(getRequiredPermission(trigger)).toEqual(value);
  });

  it('returns null for unknown trigger', () => {
    expect(getRequiredPermission('not_a_real_trigger')).toBeNull();
  });
});
