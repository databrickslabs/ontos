import type { TFunction } from 'i18next';

import type { ApiResponse } from '@/hooks/use-api';

/**
 * The error of saving a compliance policy, in the user's language when the
 * backend sent a code for it (`compliance:saveErrors.<code>`); otherwise, or
 * for an unknown code, the API's message, and `fallback` when it sent none.
 */
export function complianceSaveErrorText(
  t: TFunction,
  response: Pick<ApiResponse<unknown>, 'error' | 'errorCode' | 'errorParams'>,
  fallback = '',
): string {
  const defaultValue = response.error || fallback;
  if (!response.errorCode) return defaultValue;
  return t(`compliance:saveErrors.${response.errorCode}`, {
    ...(response.errorParams ?? {}),
    defaultValue,
  }) as string;
}
