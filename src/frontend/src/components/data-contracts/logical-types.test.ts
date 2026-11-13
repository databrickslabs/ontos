/** The date format options (format, timezone) apply to every ODCS date-like type. */
import { describe, it, expect } from 'vitest'
import { hasDateConstraints, takesTimezoneName } from './logical-types'

describe('hasDateConstraints', () => {
  it('is true for date, timestamp and time', () => {
    expect(['date', 'timestamp', 'time'].map(hasDateConstraints)).toEqual([true, true, true])
  })

  it('is false for the other types', () => {
    expect(['string', 'number', 'integer', 'array', '', undefined].map(hasDateConstraints))
      .toEqual([false, false, false, false, false, false])
  })
})

describe('takesTimezoneName', () => {
  // ODCS v3.1 types timezone as a boolean on timestamp / time (the zone goes in defaultTimezone)
  it('keeps the free-text timezone off timestamp and time', () => {
    expect(['date', 'timestamp', 'time'].map(takesTimezoneName)).toEqual([true, false, false])
  })
})
