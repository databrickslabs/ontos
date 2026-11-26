import { useMemo } from 'react';
import { usePermissions } from '@/stores/permissions-store';
import { useUserStore } from '@/stores/user-store';
import type { AppRole } from '@/types/settings';

/**
 * Ontos admin = the user holds any AppRole flagged is_admin, by group (`assigned_groups`) or
 * by email (`assigned_users`, role approval #760). Mirrors
 * AuthorizationManager.is_user_ontos_admin on the backend; NOT settings:ADMIN, see #404.
 * Comparison is case-insensitive (and trimmed for the email): the role fields and the user's
 * groups/email may come from different sources (settings.yaml vs SCIM/identity headers).
 * The roles endpoint returns the full list to an admin, `assigned_users` included, so an
 * admin assigned by user is recognised here (#1713).
 */
export function isOntosAdmin(
  groups: (string | null)[] | null | undefined,
  roles: AppRole[],
  email?: string | null,
): boolean {
  const groupSet = new Set((groups || []).map((g) => (g || '').toLowerCase()));
  const emailNorm = (email || '').trim().toLowerCase();
  if (groupSet.size === 0 && !emailNorm) return false;
  return roles.some(
    (role) =>
      role.is_admin === true &&
      ((role.assigned_groups || []).some((g) => groupSet.has((g || '').toLowerCase())) ||
        (emailNorm !== '' &&
          (role.assigned_users || []).some((u) => (u || '').trim().toLowerCase() === emailNorm))),
  );
}

/**
 * The roles the user holds: by group (`assigned_groups`) or by email (`assigned_users`),
 * case-insensitive. Mirrors the backend `_role_matches` (#1713).
 */
export function rolesHeldBy(
  groups: (string | null)[] | null | undefined,
  roles: AppRole[],
  email?: string | null,
): AppRole[] {
  const groupSet = new Set((groups || []).map((g) => (g || '').toLowerCase()));
  const emailNorm = (email || '').trim().toLowerCase();
  return roles.filter(
    (role) =>
      (role.assigned_groups || []).some((g) => groupSet.has((g || '').toLowerCase())) ||
      (emailNorm !== '' &&
        (role.assigned_users || []).some((u) => (u || '').trim().toLowerCase() === emailNorm)),
  );
}

/** Whether the current user is an Ontos admin, from the shared user and permissions stores. */
export function useIsOntosAdmin(): boolean {
  const groups = useUserStore((state) => state.userInfo?.groups);
  const email = useUserStore((state) => state.userInfo?.email);
  const { availableRoles } = usePermissions();
  return useMemo(
    () => isOntosAdmin(groups, availableRoles, email),
    [groups, email, availableRoles],
  );
}
