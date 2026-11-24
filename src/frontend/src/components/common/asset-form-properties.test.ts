/**
 * Editing an asset in its form dialog changes only the properties the user
 * edited: the stored ones the form doesn't show (a column's data_type,
 * nullable, ...) are kept.
 */
import { describe, it, expect } from 'vitest'
import { mergeEditedProperties, newAssetProperties } from './asset-form-properties'

const STORED = { data_type: 'DATE', nullable: true, comment: 'Order day' }

describe('mergeEditedProperties', () => {
  it('keeps the stored properties the form does not show', () => {
    const defaults = { prop_isNullable: false, prop_isPrimaryKey: false, prop_classification: '' }
    const values = { ...defaults, prop_isPrimaryKey: true }

    expect(mergeEditedProperties(STORED, values, defaults)).toEqual({
      ...STORED,
      isPrimaryKey: true,
    })
  })

  it('does not write untouched fields', () => {
    const defaults = { prop_isNullable: false, prop_classification: '' }

    expect(mergeEditedProperties(STORED, { ...defaults }, defaults)).toEqual(STORED)
  })

  it('removes a property the user cleared', () => {
    const stored = { ...STORED, classification: 'internal' }
    const defaults = { prop_classification: 'internal' }

    expect(mergeEditedProperties(stored, { prop_classification: '' }, defaults)).toEqual(STORED)
  })

  it('changes an edited stored property and ignores non-property fields', () => {
    const stored = { ...STORED, classification: 'internal' }
    const defaults = { name: 'a', prop_classification: 'internal' }
    const values = { name: 'b', prop_classification: 'restricted' }

    expect(mergeEditedProperties(stored, values, defaults)).toEqual({
      ...STORED,
      classification: 'restricted',
    })
  })

  it('works when the asset has no properties yet', () => {
    expect(mergeEditedProperties(null, { prop_owner: 'x' }, { prop_owner: '' })).toEqual({
      owner: 'x',
    })
  })
})

describe('newAssetProperties', () => {
  it('keeps the non-empty property fields, false included', () => {
    const values = { name: 'a', prop_owner: 'x', prop_note: '', prop_isPrimaryKey: false }
    expect(newAssetProperties(values)).toEqual({ owner: 'x', isPrimaryKey: false })
  })
})

describe('mergeEditedProperties with stored nulls', () => {
  it('drops a stored null the user left untouched', () => {
    const stored = { data_type: 'DATE', classification: null, isPrimaryKey: null }
    const defaults = { prop_classification: '', prop_isPrimaryKey: false }

    expect(mergeEditedProperties(stored, { ...defaults }, defaults)).toEqual({ data_type: 'DATE' })
  })
})
