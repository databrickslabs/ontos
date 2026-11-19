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

/** The details code of a result not evaluated because a source could not be read. */
const NOT_EVALUATED_CODE = 'rule_field_unavailable';

function resultDetailsCode(detailsJson?: string | null): unknown {
  if (!detailsJson) return undefined;
  try {
    return JSON.parse(detailsJson)?.code;
  } catch {
    return undefined;
  }
}

/** Status of one result: passed, failed, or not evaluated (neither, and out of the score). */
export function complianceResultStatus(
  t: TFunction,
  result: ComplianceResultMessageFields & { passed: boolean },
): { label: string; variant: 'secondary' | 'destructive' | 'outline' } {
  if (result.passed) return { label: t('compliance:results.passed'), variant: 'secondary' };
  if (resultDetailsCode(result.details_json) === NOT_EVALUATED_CODE) {
    return { label: t('compliance:tableSources.notEvaluatedStatus'), variant: 'outline' };
  }
  return { label: t('compliance:results.failed'), variant: 'destructive' };
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
  if (details?.code !== NOT_EVALUATED_CODE) return fallback;
  const params = details.params ?? {};
  return t('compliance:tableSources.notEvaluated', {
    ...params,
    reason: reasonsText(t, params.reason),
    defaultValue: fallback,
  }) as string;
}

/** The score and coverage of a run, as the API returns them. */
export interface ComplianceRunScoreFields {
  score?: number | null;
  coverage?: { evaluated?: number; not_evaluated?: number } | null;
}

/**
 * The score of a run ("85%"), or "No score" for a run that has none: it failed,
 * or evaluated no object (all not evaluated, or none matched).
 */
export function complianceRunScoreText(t: TFunction, run: ComplianceRunScoreFields): string {
  if (run.score === null || run.score === undefined) {
    return t('compliance:runScoreCoverage.noScore') as string;
  }
  return `${run.score}%`;
}

/**
 * The text color of a compliance score: green from 90, yellow from 70, red below,
 * and muted for no score (a policy whose recent runs failed or evaluated nothing).
 */
export function complianceScoreColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return 'text-muted-foreground';
  if (score >= 90) return 'text-green-600 dark:text-green-400';
  if (score >= 70) return 'text-yellow-600 dark:text-yellow-400';
  return 'text-red-600 dark:text-red-400';
}

/**
 * How many objects the score is measured on, when some were not evaluated
 * ("50 of 5000 objects evaluated"); an empty string when all were.
 */
export function complianceRunCoverageText(t: TFunction, run: ComplianceRunScoreFields): string {
  const evaluated = run.coverage?.evaluated ?? 0;
  const notEvaluated = run.coverage?.not_evaluated ?? 0;
  if (!notEvaluated) return '';
  return t('compliance:runScoreCoverage.coverage', {
    evaluated,
    total: evaluated + notEvaluated,
  }) as string;
}

/** The note for results on objects the viewer can't read; empty when there are none. */
export function complianceHiddenResultsText(t: TFunction, hiddenCount?: number | null): string {
  if (!hiddenCount) return '';
  return t('compliance:runScoreCoverage.hiddenResults', { count: hiddenCount }) as string;
}
