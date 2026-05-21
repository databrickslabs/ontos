/**
 * Tests for AppRole.assigned_groups normalisation.
 *
 * Covers the Phase-2 acceptance criterion: pre-existing Roles
 * ``assigned_groups`` strings still render and save without UI breakage.
 */

import { describe, expect, it } from 'vitest';

import { normaliseAssignedGroups } from './assigned-groups';

describe('normaliseAssignedGroups', () => {
  it('returns an array unchanged when already an array of strings', () => {
    expect(normaliseAssignedGroups(['data-producers', 'data-stewards'])).toEqual([
      'data-producers',
      'data-stewards',
    ]);
  });

  it('drops empty strings from an array', () => {
    expect(normaliseAssignedGroups(['a', '', 'b'])).toEqual(['a', 'b']);
  });

  it('splits a legacy comma-separated string and trims whitespace', () => {
    expect(normaliseAssignedGroups('data-producers, data-stewards , compliance')).toEqual([
      'data-producers',
      'data-stewards',
      'compliance',
    ]);
  });

  it('drops trailing / repeated commas', () => {
    expect(normaliseAssignedGroups('a,,b,')).toEqual(['a', 'b']);
  });

  it('returns [] for nullish / non-string-non-array inputs', () => {
    expect(normaliseAssignedGroups(null)).toEqual([]);
    expect(normaliseAssignedGroups(undefined)).toEqual([]);
    expect(normaliseAssignedGroups(42)).toEqual([]);
    expect(normaliseAssignedGroups({})).toEqual([]);
  });

  it('returns [] for an empty string', () => {
    expect(normaliseAssignedGroups('')).toEqual([]);
  });
});
