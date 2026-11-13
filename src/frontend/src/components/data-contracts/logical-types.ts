/** The ODCS logical types that take the date constraints (format, timezone). */
const DATE_LIKE_LOGICAL_TYPES = new Set(['date', 'timestamp', 'time'])

export function hasDateConstraints(logicalType?: string): boolean {
  return !!logicalType && DATE_LIKE_LOGICAL_TYPES.has(logicalType)
}
