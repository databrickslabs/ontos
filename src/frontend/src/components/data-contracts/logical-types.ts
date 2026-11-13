/** The ODCS logical types that take the date constraints (format, timezone). */
const DATE_LIKE_LOGICAL_TYPES = new Set(['date', 'timestamp', 'time'])

export function hasDateConstraints(logicalType?: string): boolean {
  return !!logicalType && DATE_LIKE_LOGICAL_TYPES.has(logicalType)
}


/**
 * Whether the free-text Timezone field applies. ODCS v3.1 types `timezone` as a
 * boolean on timestamp / time (the zone name goes in `defaultTimezone`), so a
 * zone name there fails validation; the field stays on date as before.
 */
export function takesTimezoneName(logicalType?: string): boolean {
  return logicalType === 'date'
}
