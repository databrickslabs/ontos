import type { TFunction } from 'i18next';

/** The fields of a compliance run that describe why it failed. */
export interface ComplianceRunErrorFields {
  error_code?: string | null;
  error_params?: Record<string, unknown> | null;
}

/**
 * Why a run failed, in the user's language (``compliance:runErrors.<code>``,
 * then ``compliance:llmCheck.errors.<code>`` for the LLM_CHECK refusals a run
 * shares with the save, such as ``llm_check_tag_action``).
 * The backend sends a code for every failed run (``run_failed`` when the error
 * has none of its own), never the error text; a code without a translation
 * shows the generic ``run_failed`` text.
 */
export function complianceRunErrorText(t: TFunction, run: ComplianceRunErrorFields): string {
  const generic = t('compliance:runErrors.run_failed') as string;
  if (!run.error_code) return generic;
  return t([
    `compliance:runErrors.${run.error_code}`,
    `compliance:llmCheck.errors.${run.error_code}`,
  ], {
    ...(run.error_params ?? {}),
    defaultValue: generic,
  }) as string;
}
