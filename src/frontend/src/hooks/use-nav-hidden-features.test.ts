import { describe, it, expect } from 'vitest';
import { resolveNavHiddenFeatures } from './use-nav-hidden-features';
import { isOntosAdmin } from './use-is-ontos-admin';
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

  it('is false without groups', () => {
    expect(isOntosAdmin(null, roles)).toBe(false);
    expect(isOntosAdmin([], roles)).toBe(false);
  });
});
