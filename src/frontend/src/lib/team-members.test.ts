/**
 * Tests for the Phase 3 team-member helpers.
 *
 * - principalAcceptsForMemberType pins the Teams row's picker filter to
 *   the chosen member_type. This is the Phase 3 acceptance criterion
 *   "switching member_type from user to group resets the picker's
 *   accepts filter".
 * - buildContractTeamMember pins the dual ``username`` + ``email``
 *   population that keeps the ODCS endpoint happy after migration.
 */

import { describe, expect, it } from 'vitest';

import {
  buildContractTeamMember,
  principalAcceptsForMemberType,
} from './team-members';

describe('principalAcceptsForMemberType', () => {
  it('returns ["user"] for "user"', () => {
    expect(principalAcceptsForMemberType('user')).toEqual(['user']);
  });

  it('returns ["group"] for "group"', () => {
    expect(principalAcceptsForMemberType('group')).toEqual(['group']);
  });

  it('defaults to ["user"] for null / undefined / unknown values', () => {
    expect(principalAcceptsForMemberType(null)).toEqual(['user']);
    expect(principalAcceptsForMemberType(undefined)).toEqual(['user']);
    expect(principalAcceptsForMemberType('')).toEqual(['user']);
    expect(principalAcceptsForMemberType('robot')).toEqual(['user']);
  });
});

describe('buildContractTeamMember', () => {
  it('populates both username and email with the picked principal id', () => {
    expect(
      buildContractTeamMember({
        emailOrUsername: 'alice@example.com',
        role: 'Data Owner',
        name: 'Alice',
      }),
    ).toEqual({
      username: 'alice@example.com',
      email: 'alice@example.com',
      role: 'Data Owner',
      name: 'Alice',
    });
  });

  it('trims surrounding whitespace on every field', () => {
    expect(
      buildContractTeamMember({
        emailOrUsername: '  bob@x  ',
        role: '  Steward  ',
        name: '  Bob  ',
      }),
    ).toEqual({
      username: 'bob@x',
      email: 'bob@x',
      role: 'Steward',
      name: 'Bob',
    });
  });

  it('omits name entirely when blank / undefined', () => {
    const m1 = buildContractTeamMember({
      emailOrUsername: 'c@x',
      role: 'r',
      name: '   ',
    });
    expect(m1).toEqual({ username: 'c@x', email: 'c@x', role: 'r' });
    expect('name' in m1).toBe(false);

    const m2 = buildContractTeamMember({ emailOrUsername: 'd@x', role: 'r' });
    expect(m2).toEqual({ username: 'd@x', email: 'd@x', role: 'r' });
    expect('name' in m2).toBe(false);
  });
});
