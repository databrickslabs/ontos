import i18n from 'i18next';

/**
 * Codes of the asset access errors of the notes, links, documents and costs
 * routes (`{detail: {code, message, params}}`), with their translation keys.
 */
const ASSET_ACCESS_KEYS: Record<string, string> = {
  asset_read_denied: 'errors:assetAccess.readDenied',
  asset_write_denied: 'errors:assetAccess.writeDenied',
  asset_not_found: 'errors:assetAccess.notFound',
};

const parsed = (body: unknown): any => {
  if (typeof body !== 'string') return body;
  try {
    return JSON.parse(body);
  } catch {
    return null;
  }
};

/**
 * The text of an asset access error in the user's language, or `null` for any
 * other error. Takes the parsed JSON body or its raw text.
 */
export function assetAccessErrorText(body: unknown): string | null {
  const error = parsed(body);
  const detail = error && typeof error === 'object' ? error.detail : null;
  if (!detail || typeof detail !== 'object') return null;
  const key = ASSET_ACCESS_KEYS[detail.code];
  if (!key) return null;
  const english = typeof detail.message === 'string' ? detail.message : '';
  if (!i18n.isInitialized) return english || null;
  const params = detail.params && typeof detail.params === 'object' ? detail.params : {};
  return String(i18n.t(key, { ...params, defaultValue: english }));
}

/**
 * The error to show for a failed response: an asset access error in the
 * user's language; otherwise `fallback`, or the body as the API sent it.
 */
export async function responseErrorText(response: Response, fallback?: string): Promise<string> {
  let body = '';
  try {
    body = await response.text();
  } catch {
    body = '';
  }
  return assetAccessErrorText(body) ?? fallback ?? body;
}
