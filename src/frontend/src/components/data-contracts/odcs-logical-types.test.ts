import { describe, it, expect } from 'vitest'
import { hasV31LogicalTypes, inferSchemaQuery, logicalTypesForVersion } from './odcs-logical-types'

describe('ODCS logical types by apiVersion', () => {
  it.each([
    [undefined, true], ['v3.1.0', true], ['3.1.0', true], ['v3.2.0', true], ['odd', true],
    ['v3.0.2', false], ['3.0.0', false], ['v2.2.2', false],
  ])('%s has the v3.1 types: %s', (apiVersion, expected) => {
    expect(hasV31LogicalTypes(apiVersion)).toBe(expected)
  })

  it('lists timestamp and time from v3.1.0 only', () => {
    expect(logicalTypesForVersion('v3.1.0')).toContain('timestamp')
    expect(logicalTypesForVersion('v3.0.2')).toEqual(
      ['string', 'date', 'number', 'integer', 'object', 'array', 'boolean'],
    )
  })

  it('keeps a stored v3.1 type visible on an older contract', () => {
    expect(logicalTypesForVersion('v3.0.2', 'timestamp')).toContain('timestamp')
    expect(logicalTypesForVersion('v3.0.2', 'timestamp')).not.toContain('time')
  })

  it('passes the apiVersion to infer-schema', () => {
    expect(inferSchemaQuery('v3.0.2')).toBe('?api_version=v3.0.2')
    expect(inferSchemaQuery(undefined)).toBe('')
  })
})
