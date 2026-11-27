/**
 * Text for a connector error code from the API (e.g. `tableau_unreachable`).
 *
 * The server sends codes, not raw error messages, so the text comes from the
 * `settings:connectors.errorCodes` keys. An unknown or missing code shows the fallback.
 */
export function connectorErrorText(
  t: (key: string, options?: { defaultValue?: string }) => string,
  code: string | null | undefined,
  fallback: string,
): string {
  if (!code) return fallback;
  return t(`settings:connectors.errorCodes.${code}`, { defaultValue: fallback });
}
