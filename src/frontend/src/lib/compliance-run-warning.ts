import type { TFunction } from 'i18next';

/** The fields of a compliance run that describe what a finished run has to tell. */
export interface ComplianceRunWarningFields {
  warning_code?: string | null;
  warning_params?: Record<string, unknown> | null;
}

/**
 * The warning of a run that finished, in the user's language
 * (`compliance:runWarnings.<code>`); an empty string when the run has none.
 * An unknown code is shown as the code itself.
 */
export function complianceRunWarningText(t: TFunction, run: ComplianceRunWarningFields): string {
  if (!run.warning_code) return '';
  return t(`compliance:runWarnings.${run.warning_code}`, {
    ...(run.warning_params ?? {}),
    defaultValue: run.warning_code,
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
