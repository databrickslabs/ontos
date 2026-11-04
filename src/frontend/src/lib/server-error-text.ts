import i18n from 'i18next';

/** Code of an unexpected server error; the backend keeps the exception's text in its log. */
export const INTERNAL_ERROR_CODE = 'internal_error';

const parsed = (body: unknown): any => {
  if (typeof body !== 'string') return body;
  try {
    return JSON.parse(body);
  } catch {
    return null;
  }
};

/**
 * The text of an unexpected server error (`{detail, code: 'internal_error',
 * params: {errorId}}`) in the user's language, or `null` for any other error.
 * Takes the parsed JSON body or its raw text.
 */
export function internalErrorText(body: unknown): string | null {
  const error = parsed(body);
  if (!error || typeof error !== 'object' || error.code !== INTERNAL_ERROR_CODE) return null;
  const english = typeof error.detail === 'string' ? error.detail : '';
  if (!i18n.isInitialized) return english || null;
  const params = error.params && typeof error.params === 'object' ? error.params : {};
  return String(i18n.t('errors:internalError', { ...params, defaultValue: english }));
}

/** Code of a request that needs the user's Databricks token and has none. */
export const USER_TOKEN_REQUIRED_CODE = 'user_token_required';

/**
 * The text of a request refused for a missing user token
 * (`{detail: {code: 'user_token_required', message}}`) in the user's language,
 * or `null` for any other error. Takes the parsed JSON body or its raw text.
 */
export function userTokenRequiredText(body: unknown): string | null {
  const error = parsed(body);
  const detail = error && typeof error === 'object' ? error.detail : null;
  if (!detail || typeof detail !== 'object' || detail.code !== USER_TOKEN_REQUIRED_CODE) {
    return null;
  }
  const english = typeof detail.message === 'string' ? detail.message : '';
  if (!i18n.isInitialized) return english || null;
  return String(i18n.t('errors:userTokenRequired', { defaultValue: english }));
}

/**
 * An app-wide server error (an unexpected error, a missing user token) in the
 * user's language, or `null` for any other error.
 */
export function serverErrorText(body: unknown): string | null {
  return internalErrorText(body) ?? userTokenRequiredText(body);
}
