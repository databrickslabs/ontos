import { useMemo } from 'react';
import { usePermissions } from '@/stores/permissions-store';
import { useIsOntosAdmin } from '@/hooks/use-is-ontos-admin';

const NOTHING_HIDDEN: ReadonlySet<string> = new Set<string>();

/**
 * Feature ids the menus (sidebar, home quick actions, About) leave out (#1325).
 *
 * The backend resolves them from the user's roles like the permissions
 * (`GET /api/user/navigation`). An Ontos admin acting as themselves sees every
 * feature; once they switch to another role they see that role's menu. Hiding
 * changes only the menus: pages stay reachable by link with the same access.
 */
export function resolveNavHiddenFeatures(
  hiddenFeatures: readonly string[] | undefined,
  isOntosAdmin: boolean,
  appliedRoleId: string | null | undefined,
): ReadonlySet<string> {
  if ((isOntosAdmin && !appliedRoleId) || !hiddenFeatures?.length) return NOTHING_HIDDEN;
  return new Set(hiddenFeatures);
}

export function useNavHiddenFeatures(): ReadonlySet<string> {
  const isAdmin = useIsOntosAdmin();
  const { hiddenNavFeatures, appliedRoleId } = usePermissions();
  return useMemo(
    () => resolveNavHiddenFeatures(hiddenNavFeatures, isAdmin, appliedRoleId),
    [hiddenNavFeatures, isAdmin, appliedRoleId],
  );
}
