import type { TFunction } from 'i18next';

/** The fields of a compliance run that describe why it failed. */
export interface ComplianceRunErrorFields {
  error_message?: string | null;
  error_code?: string | null;
  error_params?: Record<string, unknown> | null;
}

/**
 * Why a run failed, in the user's language when the backend sent a code for
 * it (``compliance:runErrors.<code>``); otherwise, or for an unknown code, the
 * stored English message.
 */
export function complianceRunErrorText(t: TFunction, run: ComplianceRunErrorFields): string {
  const message = run.error_message ?? '';
  if (!run.error_code) return message;
  return t(`compliance:runErrors.${run.error_code}`, {
    ...(run.error_params ?? {}),
    defaultValue: message,
  }) as string;
}
