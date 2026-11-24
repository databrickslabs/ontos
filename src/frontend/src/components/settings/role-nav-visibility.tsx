import { useTranslation } from 'react-i18next';
import { Checkbox } from '@/components/ui/checkbox';
import { FeatureAccessLevel } from '@/types/settings';

/** Width of the "Show in navigation" column in the role editor. */
export const NAV_COLUMN_CLASS = 'w-[110px]';

/**
 * The hidden list to store for a role (#1325): known features only, and never one at
 * None (it has no menu entry anyway).
 */
export function cleanHiddenNavFeatures(
  hidden: readonly string[] | undefined,
  permissions: Record<string, FeatureAccessLevel> | undefined,
  knownFeatureIds: Iterable<string>,
): string[] {
  const known = new Set(knownFeatureIds);
  return Array.from(new Set(hidden || [])).filter(
    (id) => known.has(id)
      && (permissions?.[id] ?? FeatureAccessLevel.NONE) !== FeatureAccessLevel.NONE,
  );
}

/**
 * The text of a failed role save: the unknown-feature refusal (#1325) in the user's
 * language, else the API's error text. Null when the save succeeded.
 */
export function roleSaveErrorText(
  response: { error?: string | null; errorCode?: string | null;
    errorParams?: Record<string, unknown> | null },
  t: (key: string, options?: Record<string, unknown>) => string,
): string | null {
  if (response.errorCode === 'role_nav_feature_unknown') {
    const ids = response.errorParams?.feature_ids;
    return t('settings:roles.permissions.navigation.unknownFeatures', {
      features: Array.isArray(ids) ? ids.join(', ') : '',
    });
  }
  return response.error || null;
}

/** Help text and column titles above the role editor's permission rows. */
export function RoleNavColumnHeader() {
  const { t } = useTranslation('settings');
  return (
    <>
      <p className="text-xs text-muted-foreground" data-testid="nav-visibility-help">
        {t('roles.permissions.navigation.help')}
      </p>
      <div className="flex justify-end gap-4 text-xs font-medium text-muted-foreground">
        <span className="w-[180px] text-center">
          {t('roles.permissions.navigation.accessColumn')}
        </span>
        <span className={`${NAV_COLUMN_CLASS} text-center`}>
          {t('roles.permissions.navigation.column')}
        </span>
      </div>
    </>
  );
}

interface RoleNavVisibilityCellProps {
  featureId: string;
  label: string;
  level: FeatureAccessLevel | undefined;
  isAdminRole: boolean;
  hidden: readonly string[];
  onChange: (hidden: string[]) => void;
}

/**
 * "Show in navigation" checkbox of one role feature. Disabled at None (nothing to show)
 * and on the admin role (it always shows every feature). Visibility only: the access
 * level next to it is unchanged.
 */
export function RoleNavVisibilityCell({
  featureId, label, level, isAdminRole, hidden, onChange,
}: RoleNavVisibilityCellProps) {
  const { t } = useTranslation('settings');
  const noAccess = (level ?? FeatureAccessLevel.NONE) === FeatureAccessLevel.NONE;
  let hint: string | undefined;
  if (noAccess) hint = t('roles.permissions.navigation.noAccessHint');
  else if (isAdminRole) hint = t('roles.permissions.navigation.adminHint');
  return (
    <div className={`${NAV_COLUMN_CLASS} flex justify-center`}>
      <Checkbox
        id={`nav-${featureId}`}
        aria-label={t('roles.permissions.navigation.showFeature', { feature: label })}
        title={hint}
        checked={!noAccess && !hidden.includes(featureId)}
        disabled={noAccess || isAdminRole}
        onCheckedChange={(checked) => {
          const rest = hidden.filter((id) => id !== featureId);
          onChange(checked === true ? rest : [...rest, featureId]);
        }}
      />
    </div>
  );
}
