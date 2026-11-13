import type { TFunction } from 'i18next'

/** Code of a contract apiVersion outside ODCS (src/common/odcs_versions.py). */
export const ODCS_API_VERSION_UNSUPPORTED = 'odcs_api_version_unsupported'

const parsed = (body: unknown): any => {
  if (typeof body !== 'string') return body
  try {
    return JSON.parse(body)
  } catch {
    return null
  }
}

/**
 * The refusal of a contract apiVersion outside ODCS in the user's language, or
 * `null` for any other error. The create route answers 422 with pydantic's
 * `detail: [{type, ctx: {api_version}}]`, the update route 400 with
 * `detail: {code, params: {api_version}}`. Takes the parsed body or its text.
 */
export function odcsApiVersionErrorText(body: unknown, t: TFunction): string | null {
  const detail = parsed(body)?.detail
  let apiVersion: unknown
  if (Array.isArray(detail)) {
    const item = detail.find((d) => d && d.type === ODCS_API_VERSION_UNSUPPORTED)
    if (!item) return null
    apiVersion = item.ctx?.api_version
  } else if (detail && typeof detail === 'object' && detail.code === ODCS_API_VERSION_UNSUPPORTED) {
    apiVersion = detail.params?.api_version
  } else {
    return null
  }
  return t('data-contracts:apiVersionErrors.unsupported', { apiVersion: String(apiVersion ?? '') })
}
