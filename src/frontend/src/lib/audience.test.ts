/**
 * Tests for the audience-token round-trip used by the comment
 * composer. Covers:
 *  - the original Phase-2 acceptance criterion: "an audience containing
 *    a mix of users, groups, teams (team:*), and roles (role:*) round-trips
 *    correctly"
 *  - the issue #326 acceptance criterion: new tokens are emitted as
 *    `role_id:<uuid>`; legacy `role:<name>` tokens still parse and
 *    round-trip unchanged when no name→uuid lookup resolves them.
 */

import { describe, expect, it } from 'vitest';

import { buildAudienceTokens, parseAudienceTokens, resolveRoleTokenLabel } from './audience';

describe('parseAudienceTokens', () => {
  it('splits team:, role_id:, legacy role:, and bare principal tokens', () => {
    const parsed = parseAudienceTokens([
      'team:t-1',
      'role_id:11111111-2222-3333-4444-555555555555',
      'role:Admin', // legacy, no rolesByName provided → falls into legacyRoleNames
      'alice@x.com',
      'Data Producers',
    ]);
    expect(parsed.teams).toEqual(['t-1']);
    expect(parsed.roleIds).toEqual(['11111111-2222-3333-4444-555555555555']);
    expect(parsed.legacyRoleNames).toEqual(['Admin']);
    expect(parsed.principals).toEqual(['alice@x.com', 'Data Producers']);
  });

  it('upgrades legacy role:<name> tokens to roleIds when rolesByName resolves them', () => {
    const parsed = parseAudienceTokens(
      ['role:Admin', 'role:Unknown'],
      { Admin: 'admin-uuid' },
    );
    expect(parsed.roleIds).toEqual(['admin-uuid']);
    expect(parsed.legacyRoleNames).toEqual(['Unknown']);
  });

  it('returns empty arrays for null / undefined / empty input', () => {
    const empty = { teams: [], roleIds: [], legacyRoleNames: [], principals: [] };
    expect(parseAudienceTokens(null)).toEqual(empty);
    expect(parseAudienceTokens(undefined)).toEqual(empty);
    expect(parseAudienceTokens([])).toEqual(empty);
  });

  it('skips non-string and empty tokens', () => {
    const parsed = parseAudienceTokens([
      'team:t-1',
      '',
      // @ts-expect-error verify defensive guard
      null,
      'alice@x.com',
    ]);
    expect(parsed.teams).toEqual(['t-1']);
    expect(parsed.principals).toEqual(['alice@x.com']);
  });

  it('treats prefix-only tokens as the empty id behind the prefix', () => {
    const parsed = parseAudienceTokens(['team:', 'role_id:', 'role:']);
    // Empty ids are preserved — the caller decides whether to filter.
    expect(parsed.teams).toEqual(['']);
    expect(parsed.roleIds).toEqual(['']);
    expect(parsed.legacyRoleNames).toEqual(['']);
    expect(parsed.principals).toEqual([]);
  });
});

describe('buildAudienceTokens', () => {
  it('emits team:, role_id: (canonical), legacy role: (preserved), and bare principals', () => {
    const tokens = buildAudienceTokens({
      teams: ['t-1', 't-2'],
      roleIds: ['admin-uuid'],
      legacyRoleNames: ['LegacyName'],
      principals: ['alice@x.com', 'Data Producers'],
    });
    expect(tokens).toEqual([
      'team:t-1',
      'team:t-2',
      'role_id:admin-uuid',
      'role:LegacyName',
      'alice@x.com',
      'Data Producers',
    ]);
  });

  it('round-trips a mixed audience without loss (no legacy)', () => {
    const original = [
      'team:t-7',
      'role_id:reviewer-uuid',
      'bob@x.com',
      'Engineering',
    ];
    const parsed = parseAudienceTokens(original);
    const rebuilt = buildAudienceTokens(parsed);
    expect(rebuilt).toEqual(original);
  });

  it('preserves legacy role:<name> tokens unchanged on round-trip (no rolesByName)', () => {
    const original = ['role:Admin', 'role:DataSteward', 'alice@x.com'];
    const parsed = parseAudienceTokens(original);
    const rebuilt = buildAudienceTokens(parsed);
    expect(rebuilt).toEqual(original);
  });
});

describe('resolveRoleTokenLabel', () => {
  const rolesById = { 'admin-uuid': 'Admin', 'steward-uuid': 'Data Steward' };

  it('resolves role_id:<uuid> tokens via the lookup map', () => {
    expect(resolveRoleTokenLabel('role_id:admin-uuid', rolesById)).toBe('Admin');
  });

  it('falls back to a truncated label when the uuid is unknown', () => {
    const label = resolveRoleTokenLabel('role_id:deadbeef-1234-5678-9abc-defabcdef012', rolesById);
    expect(label).toBe('Role (deadbeef…)');
  });

  it('returns the bare name for legacy role:<name> tokens', () => {
    expect(resolveRoleTokenLabel('role:LegacyAdmin', rolesById)).toBe('LegacyAdmin');
  });

  it('returns null for non-role tokens', () => {
    expect(resolveRoleTokenLabel('team:t-1', rolesById)).toBeNull();
    expect(resolveRoleTokenLabel('alice@x.com', rolesById)).toBeNull();
  });
});
