import type { TFunction } from 'i18next';

/** Error codes the estates API sends with ``detail = {code, message, params}``. */
const ESTATE_ERROR_CODES = new Set(['estate_name_conflict']);

/**
 * The text to show for a failed estates call: the translated text of a known
 * error code, else the server's (English) message.
 */
export function estateErrorText(
  response: { error?: string | null; errorCode?: string | null; errorParams?: Record<string, unknown> | null },
  t: TFunction,
): string {
  if (response.errorCode && ESTATE_ERROR_CODES.has(response.errorCode)) {
    return t(`estates:errors.codes.${response.errorCode}`, {
      ...(response.errorParams || {}),
      defaultValue: response.error || '',
    });
  }
  return response.error || '';
}
