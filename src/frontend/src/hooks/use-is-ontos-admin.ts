import { useMemo } from 'react';
import { usePermissions } from '@/stores/permissions-store';
import { useUserStore } from '@/stores/user-store';
import type { AppRole } from '@/types/settings';

/**
 * Ontos admin = the user belongs to any AppRole flagged is_admin (mirrors
 * AuthorizationManager.is_user_ontos_admin on the backend; NOT settings:ADMIN, see #404).
 * Group comparison is case-insensitive: `assigned_groups` and the user's groups may come
 * from different sources (settings.yaml vs SCIM/identity headers).
 */
export function isOntosAdmin(
  groups: (string | null)[] | null | undefined,
  roles: AppRole[],
): boolean {
  if (!groups || groups.length === 0) return false;
  const groupSet = new Set(groups.map((g) => (g || '').toLowerCase()));
  return roles.some(
    (role) =>
      role.is_admin === true &&
      (role.assigned_groups || []).some((g) => groupSet.has((g || '').toLowerCase())),
  );
}

/** Whether the current user is an Ontos admin, from the shared user and permissions stores. */
export function useIsOntosAdmin(): boolean {
  const groups = useUserStore((state) => state.userInfo?.groups);
  const { availableRoles } = usePermissions();
  return useMemo(() => isOntosAdmin(groups, availableRoles), [groups, availableRoles]);
}
