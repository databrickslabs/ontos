import type { TFunction } from 'i18next';

/** The fields of a compliance run that describe what a finished run has to tell. */
export interface ComplianceRunWarningFields {
  warning_code?: string | null;
  warning_params?: Record<string, unknown> | null;
}

/** The fields of a compliance result that describe why it passed or failed. */
export interface ComplianceResultMessageFields {
  message?: string | null;
  details_json?: string | null;
}

/** Warning codes whose text lives outside `compliance:runWarnings`. */
const WARNING_KEYS: Record<string, string> = {
  rule_fields_unavailable: 'compliance:tableSources.runWarning',
};

/** Comma-separated reason codes of an unreadable source, in the user's language. */
function reasonsText(t: TFunction, reasons: unknown): string {
  return String(reasons ?? '')
    .split(',')
    .map((code) => code.trim())
    .filter(Boolean)
    .map((code) => t(`compliance:tableSources.reasons.${code}`, { defaultValue: code }) as string)
    .join(', ');
}

/**
 * The warning of a run that finished, in the user's language
 * (`compliance:runWarnings.<code>`); an empty string when the run has none.
 * An unknown code is shown as the code itself.
 */
export function complianceRunWarningText(t: TFunction, run: ComplianceRunWarningFields): string {
  if (!run.warning_code) return '';
  const params = { ...(run.warning_params ?? {}) };
  if ('reasons' in params) params.reasons = reasonsText(t, params.reasons);
  const key = WARNING_KEYS[run.warning_code] ?? `compliance:runWarnings.${run.warning_code}`;
  return t(key, { ...params, defaultValue: run.warning_code }) as string;
}

/**
 * The message of one result: translated when the backend gave it a code in
 * `details_json` (an object not evaluated because a source could not be read),
 * else the stored message.
 */
export function complianceResultMessageText(
  t: TFunction,
  result: ComplianceResultMessageFields,
): string {
  const fallback = result.message ?? '';
  if (!result.details_json) return fallback;
  let details: { code?: unknown; params?: Record<string, unknown> };
  try {
    details = JSON.parse(result.details_json);
  } catch {
    return fallback;
  }
  if (details?.code !== 'rule_field_unavailable') return fallback;
  const params = details.params ?? {};
  return t('compliance:tableSources.notEvaluated', {
    ...params,
    reason: reasonsText(t, params.reason),
    defaultValue: fallback,
  }) as string;
}
