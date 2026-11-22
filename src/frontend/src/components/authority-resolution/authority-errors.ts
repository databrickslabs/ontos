/**
 * Maps the coded Authority Resolution errors (`detail: {code, message, params}`)
 * to translated text. Unknown codes fall back to the server message.
 */
type Translate = (key: string, options?: any) => string;

// Reasons of a 409 authority_status_conflict (params.reason).
export const STATUS_CONFLICT_REASONS = [
  'no_enabled_checks',
  'not_measured',
  'dna_stale',
  'ceiling_exceeded',
  'affirmations_missing',
  'affirmations_stale',
  'transition_not_allowed',
] as const;

export function authorityErrorMessage(
  t: Translate,
  error: string | null | undefined,
  code?: string | null,
  params?: Record<string, unknown> | null,
): string {
  const fallback = error || t('errors.generic');
  switch (code) {
    case 'authority_immutable':
      return t('errors.immutable');
    case 'authority_has_history':
      return t('errors.hasHistory');
    case 'authority_duplicate_version':
      return t('errors.duplicateVersion', { version: String(params?.version ?? '') });
    case 'authority_invalid_version':
      return t('errors.invalidVersion');
    case 'authority_self_affirmation':
      return t('errors.selfAffirmation');
    case 'authority_permission_denied':
      return t('errors.permissionDenied');
    case 'authority_status_conflict': {
      const reason = typeof params?.reason === 'string' ? params.reason : '';
      return (STATUS_CONFLICT_REASONS as readonly string[]).includes(reason)
        ? t(`errors.statusConflict.${reason}`)
        : fallback;
    }
    default:
      return fallback;
  }
}
