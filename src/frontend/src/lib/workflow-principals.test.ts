/**
 * Tests for the Workflow Designer's role-token + custom-principals
 * round-trip. The acceptance criterion (Phase 4) is that the toggle
 * is purely additive: a role-only config persists and re-hydrates
 * with no principals; a role + picked principals persists as a
 * single comma-separated string and re-hydrates losslessly.
 */

import { describe, expect, it } from 'vitest';

import {
  joinRoleAndPrincipals,
  roleSelectValue,
  splitRoleAndPrincipals,
} from './workflow-principals';

describe('joinRoleAndPrincipals', () => {
  it('returns the role alone when no principals are picked', () => {
    expect(joinRoleAndPrincipals('DomainOwner', [])).toBe('DomainOwner');
    expect(joinRoleAndPrincipals('requester', [])).toBe('requester');
  });

  it('returns the principals alone when no role is selected', () => {
    expect(joinRoleAndPrincipals('', ['alice@x.com', 'Producers'])).toBe(
      'alice@x.com,Producers',
    );
    expect(joinRoleAndPrincipals(null, ['alice@x.com'])).toBe('alice@x.com');
  });

  it('joins role and principals with commas', () => {
    expect(
      joinRoleAndPrincipals('owner', ['alice@x.com', 'Producers']),
    ).toBe('owner,alice@x.com,Producers');
  });

  it('dedupes repeats', () => {
    expect(
      joinRoleAndPrincipals('alice@x.com', ['alice@x.com', 'Producers']),
    ).toBe('alice@x.com,Producers');
  });

  it('strips whitespace and skips empties', () => {
    expect(
      joinRoleAndPrincipals('  owner  ', ['  alice@x.com  ', '', '  Producers']),
    ).toBe('owner,alice@x.com,Producers');
  });
});

describe('splitRoleAndPrincipals', () => {
  it('returns empty fields for null / undefined / empty', () => {
    expect(splitRoleAndPrincipals(null)).toEqual({ roleToken: '', principals: [] });
    expect(splitRoleAndPrincipals(undefined)).toEqual({ roleToken: '', principals: [] });
    expect(splitRoleAndPrincipals('')).toEqual({ roleToken: '', principals: [] });
  });

  it('recognises role literals as the role token', () => {
    expect(splitRoleAndPrincipals('requester')).toEqual({
      roleToken: 'requester',
      principals: [],
    });
    expect(splitRoleAndPrincipals('owner')).toEqual({
      roleToken: 'owner',
      principals: [],
    });
  });

  it('recognises legacy role aliases', () => {
    expect(splitRoleAndPrincipals('domain_owners')).toEqual({
      roleToken: 'domain_owners',
      principals: [],
    });
  });

  it('recognises business: prefixed business roles', () => {
    expect(splitRoleAndPrincipals('business:abc')).toEqual({
      roleToken: 'business:abc',
      principals: [],
    });
  });

  it('recognises UUID-shaped role tokens', () => {
    const uuid = '01234567-89ab-cdef-0123-456789abcdef';
    expect(splitRoleAndPrincipals(uuid)).toEqual({
      roleToken: uuid,
      principals: [],
    });
  });

  it('puts non-role entries into principals', () => {
    expect(splitRoleAndPrincipals('alice@x.com,Producers')).toEqual({
      roleToken: '',
      principals: ['alice@x.com', 'Producers'],
    });
  });

  it('splits a role + principals string back out losslessly', () => {
    expect(splitRoleAndPrincipals('owner,alice@x.com,Producers')).toEqual({
      roleToken: 'owner',
      principals: ['alice@x.com', 'Producers'],
    });
  });

  it('round-trips identity for join->split->join', () => {
    const cases: Array<[string, string[]]> = [
      ['DomainOwner', []],
      ['', ['alice@x.com']],
      ['owner', ['alice@x.com', 'Producers']],
      ['requester', ['some-group']],
    ];
    for (const [role, picks] of cases) {
      const joined = joinRoleAndPrincipals(role, picks);
      const split = splitRoleAndPrincipals(joined);
      const rejoined = joinRoleAndPrincipals(split.roleToken, split.principals);
      expect(rejoined).toBe(joined);
    }
  });

  it('preserves extra role-shaped tokens as principal entries after the first', () => {
    // If somehow two role-shaped tokens appear (e.g. legacy data) the
    // first wins the slot and the rest fall into the picker side so
    // the user can see and remove them.
    expect(splitRoleAndPrincipals('requester,owner,alice@x.com')).toEqual({
      roleToken: 'requester',
      principals: ['owner', 'alice@x.com'],
    });
  });
});

describe('shipped role names', () => {
  const roles = [
    { id: 'r-steward', name: 'DataSteward' },
    { id: 'r-sec', name: 'Security Officer' },
  ];

  it('treats a role name as the role token, not a custom principal', () => {
    expect(splitRoleAndPrincipals('DataSteward', roles)).toEqual({
      roleToken: 'DataSteward',
      principals: [],
    });
    expect(splitRoleAndPrincipals('datasteward,alice@x.com', roles)).toEqual({
      roleToken: 'datasteward',
      principals: ['alice@x.com'],
    });
  });

  it('treats owner-derived tokens as roles, whatever their spelling', () => {
    for (const tok of ['DomainOwner', 'domain_owners', 'ContractApprover']) {
      expect(splitRoleAndPrincipals(tok, roles)).toEqual({ roleToken: tok, principals: [] });
    }
    expect(splitRoleAndPrincipals('DomainOwner,alice@x.com', roles)).toEqual({
      roleToken: 'DomainOwner',
      principals: ['alice@x.com'],
    });
  });

  it('keeps the stored value when re-joined without edits', () => {
    for (const stored of ['DomainOwner', 'domain_owners', 'ContractApprover', 'DataSteward']) {
      const split = splitRoleAndPrincipals(stored, roles);
      expect(joinRoleAndPrincipals(split.roleToken, split.principals)).toBe(stored);
    }
    // The select shows the role option but the token itself stays the name.
    expect(splitRoleAndPrincipals('DataSteward', roles).roleToken).toBe('DataSteward');
  });

  it('still treats unknown names as principals', () => {
    expect(splitRoleAndPrincipals('Producers', roles)).toEqual({
      roleToken: '',
      principals: ['Producers'],
    });
  });

  it('maps a role name to its select option, and leaves other tokens alone', () => {
    expect(roleSelectValue('DataSteward', roles)).toBe('r-steward');
    expect(roleSelectValue('requester', roles)).toBe('requester');
    expect(roleSelectValue('', roles)).toBe('');
    expect(roleSelectValue('DataSteward', undefined)).toBe('DataSteward');
  });

  it('maps owner-derived tokens to their option', () => {
    expect(roleSelectValue('DomainOwner', roles)).toBe('DomainOwner');
    expect(roleSelectValue('domain_owners', roles)).toBe('DomainOwner');
    expect(roleSelectValue('ContractApprover', undefined)).toBe('ContractApprover');
  });
});
