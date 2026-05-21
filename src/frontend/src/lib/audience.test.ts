/**
 * Tests for the audience-token round-trip used by the comment
 * composer. These cover the Phase-2 acceptance criterion:
 * "an audience containing a mix of users, groups, teams (team:*), and
 *  roles (role:*) round-trips correctly".
 */

import { describe, expect, it } from 'vitest';

import { buildAudienceTokens, parseAudienceTokens } from './audience';

describe('parseAudienceTokens', () => {
  it('splits team:, role:, and bare principal tokens', () => {
    const parsed = parseAudienceTokens([
      'team:t-1',
      'role:Admin',
      'alice@x.com',
      'Data Producers',
    ]);
    expect(parsed.teams).toEqual(['t-1']);
    expect(parsed.roles).toEqual(['Admin']);
    expect(parsed.principals).toEqual(['alice@x.com', 'Data Producers']);
  });

  it('returns empty arrays for null / undefined / empty input', () => {
    expect(parseAudienceTokens(null)).toEqual({ teams: [], roles: [], principals: [] });
    expect(parseAudienceTokens(undefined)).toEqual({ teams: [], roles: [], principals: [] });
    expect(parseAudienceTokens([])).toEqual({ teams: [], roles: [], principals: [] });
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
    const parsed = parseAudienceTokens(['team:', 'role:']);
    // Empty ids are preserved -- the caller decides whether to filter.
    expect(parsed.teams).toEqual(['']);
    expect(parsed.roles).toEqual(['']);
    expect(parsed.principals).toEqual([]);
  });
});

describe('buildAudienceTokens', () => {
  it('emits team: / role: prefixes for checkbox selections, principals bare', () => {
    const tokens = buildAudienceTokens({
      teams: ['t-1', 't-2'],
      roles: ['Admin'],
      principals: ['alice@x.com', 'Data Producers'],
    });
    expect(tokens).toEqual([
      'team:t-1',
      'team:t-2',
      'role:Admin',
      'alice@x.com',
      'Data Producers',
    ]);
  });

  it('round-trips a mixed audience without loss', () => {
    const original = [
      'team:t-7',
      'role:Reviewer',
      'bob@x.com',
      'Engineering',
    ];
    const parsed = parseAudienceTokens(original);
    const rebuilt = buildAudienceTokens(parsed);
    expect(rebuilt).toEqual(original);
  });
});
