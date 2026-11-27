import { describe, it, expect } from 'vitest';
import { resolveNavHiddenFeatures } from './use-nav-hidden-features';
import { isOntosAdmin, rolesHeldBy } from './use-is-ontos-admin';
import type { AppRole } from '@/types/settings';

describe('resolveNavHiddenFeatures', () => {
  it('hides the features the backend resolved for the user', () => {
    expect([...resolveNavHiddenFeatures(['assets', 'data-contracts'], false, null)])
      .toEqual(['assets', 'data-contracts']);
  });

  it('hides nothing for an Ontos admin acting as themselves', () => {
    expect(resolveNavHiddenFeatures(['assets'], true, null).size).toBe(0);
  });

  it("follows the switched role for an admin using the role switcher", () => {
    expect([...resolveNavHiddenFeatures(['assets'], true, 'r-consumer')]).toEqual(['assets']);
  });

  it('returns an empty set when nothing is hidden', () => {
    expect(resolveNavHiddenFeatures([], false, 'r-1').size).toBe(0);
    expect(resolveNavHiddenFeatures(undefined, false, undefined).size).toBe(0);
  });
});

describe('isOntosAdmin', () => {
  const roles = [
    { id: 'a', name: 'Admin', assigned_groups: ['Admins'], is_admin: true },
    { id: 'c', name: 'Consumer', assigned_groups: ['consumers'], is_admin: false },
  ] as AppRole[];

  it('matches an is_admin role by group, case-insensitively', () => {
    expect(isOntosAdmin(['admins'], roles)).toBe(true);
    expect(isOntosAdmin(['consumers'], roles)).toBe(false);
  });

  it('is false without groups and without email', () => {
    expect(isOntosAdmin(null, roles)).toBe(false);
    expect(isOntosAdmin([], roles)).toBe(false);
    expect(isOntosAdmin([], roles, '  ')).toBe(false);
  });

  it('matches an is_admin role assigned by user, case-insensitively, no groups (#1713)', () => {
    const byUser = [
      {
        id: 'a', name: 'Admin', assigned_groups: [],
        assigned_users: ['Boss@Example.com'], is_admin: true,
      },
    ] as unknown as AppRole[];
    expect(isOntosAdmin([], byUser, ' boss@example.COM ')).toBe(true);
    expect(isOntosAdmin(['x'], byUser, 'boss@example.com')).toBe(true);
    expect(isOntosAdmin([], byUser, 'other@example.com')).toBe(false);
  });

  it('does not treat a non-admin role assigned by user as admin', () => {
    const byUser = [
      {
        id: 'c', name: 'Consumer', assigned_groups: [],
        assigned_users: ['dev@example.com'], is_admin: false,
      },
    ] as unknown as AppRole[];
    expect(isOntosAdmin([], byUser, 'dev@example.com')).toBe(false);
  });
});

describe('rolesHeldBy', () => {
  const roles = [
    { id: 'g', name: 'ByGroup', assigned_groups: ['Team'], assigned_users: [] },
    { id: 'u', name: 'ByUser', assigned_groups: [], assigned_users: ['Dev@Example.com'] },
    { id: 'o', name: 'Other', assigned_groups: ['x'], assigned_users: ['o@example.com'] },
  ] as unknown as AppRole[];

  it('returns roles held by group or by user, case-insensitively (#1713)', () => {
    expect(rolesHeldBy(['team'], roles, ' dev@example.COM ').map((r) => r.id)).toEqual(['g', 'u']);
    expect(rolesHeldBy([], roles, 'dev@example.com').map((r) => r.id)).toEqual(['u']);
  });

  it('returns nothing without groups and email', () => {
    expect(rolesHeldBy(null, roles, null)).toEqual([]);
  });
});
