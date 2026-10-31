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
