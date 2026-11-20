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

const DATE_LIKE_LOGICAL_TYPES = new Set(['date', 'timestamp', 'time'])

/** The ODCS logical types that take the date constraints (format, custom format). */
export function hasDateConstraints(logicalType?: string): boolean {
  return !!logicalType && DATE_LIKE_LOGICAL_TYPES.has(logicalType)
}

/** `timezone` is a free-text zone name on a date column (as before). */
export function takesTimezoneName(logicalType?: string): boolean {
  return logicalType === 'date'
}

/** ODCS v3.1 types `timezone` as a boolean on timestamp and time columns. */
export function takesTimezoneFlag(logicalType?: string): boolean {
  return logicalType === 'timestamp' || logicalType === 'time'
}

/**
 * The `timezone` value a column of this logical type keeps: a trimmed string on a
 * date, a boolean on timestamp and time (a zone name there is dropped, it isn't
 * valid ODCS), anything else as it is.
 */
export function timezoneForType(
  logicalType: string | undefined, value: unknown,
): string | boolean | undefined {
  if (takesTimezoneName(logicalType)) {
    return typeof value === 'string' ? value.trim() || undefined : undefined
  }
  if (takesTimezoneFlag(logicalType)) return typeof value === 'boolean' ? value : undefined
  return typeof value === 'string' ? value.trim() || undefined : (value as boolean | undefined)
}
