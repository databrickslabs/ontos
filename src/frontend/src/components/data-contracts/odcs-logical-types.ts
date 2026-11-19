/** ODCS v3.1.0 logical types, in the order the contract editors list them. */
export const ODCS_LOGICAL_TYPES = [
  'string', 'date', 'timestamp', 'time', 'number', 'integer', 'object', 'array', 'boolean',
]

const V31_ONLY = new Set(['timestamp', 'time'])

/**
 * Whether a contract with this apiVersion may use `timestamp` and `time` (added in
 * ODCS v3.1.0). No value, or one that isn't a version, counts as v3.1.0, the
 * default of a new contract.
 */
export function hasV31LogicalTypes(apiVersion?: string | null): boolean {
  const match = /^v?(\d+)\.(\d+)(?:\.\d+)?$/.exec((apiVersion ?? '').trim().toLowerCase())
  if (!match) return true
  const [major, minor] = [Number(match[1]), Number(match[2])]
  return major > 3 || (major === 3 && minor >= 1)
}

/**
 * The logical types a contract with this apiVersion lists. Below v3.1.0 the
 * v3.1-only types are left out, except `current` (a stored value stays visible).
 */
export function logicalTypesForVersion(apiVersion?: string | null, current?: string): string[] {
  if (hasV31LogicalTypes(apiVersion)) return ODCS_LOGICAL_TYPES
  return ODCS_LOGICAL_TYPES.filter((type) => !V31_ONLY.has(type) || type === current)
}

/** The query string of `GET /api/assets/{id}/infer-schema` for a contract's apiVersion. */
export function inferSchemaQuery(apiVersion?: string | null): string {
  return apiVersion ? `?api_version=${encodeURIComponent(apiVersion)}` : ''
}

/**
 * `GET /api/schema-import/metadata/{connection}` for a table, with each column's
 * `logical_type` as an ODCS logical type for a contract's apiVersion.
 */
export function catalogMetadataUrl(
  connectionId: string, path: string, apiVersion?: string | null,
): string {
  const version = apiVersion ? `&api_version=${encodeURIComponent(apiVersion)}` : ''
  const query = `path=${encodeURIComponent(path)}&odcs=true${version}`
  return `/api/schema-import/metadata/${connectionId}?${query}`
}
