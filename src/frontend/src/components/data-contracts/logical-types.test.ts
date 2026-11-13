/** The date format options (format, custom format) apply to every ODCS date-like type. */
import { describe, it, expect } from 'vitest'
import { hasDateConstraints } from './logical-types'

describe('hasDateConstraints', () => {
  it('is true for date, timestamp and time', () => {
    expect(['date', 'timestamp', 'time'].map(hasDateConstraints)).toEqual([true, true, true])
  })

  it('is false for the other types', () => {
    expect(['string', 'number', 'integer', 'array', '', undefined].map(hasDateConstraints))
      .toEqual([false, false, false, false, false, false])
  })
})
