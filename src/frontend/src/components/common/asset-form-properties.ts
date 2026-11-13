const PROP_PREFIX = 'prop_'

const isEmpty = (val: unknown) => val === '' || val === null || val === undefined

/**
 * Properties to send when an asset is edited in its form dialog.
 *
 * The form shows only the fields of the asset type's ontology schema, while an
 * asset can store more (an imported column keeps `data_type`, `nullable`, ...).
 * Start from the stored properties and apply only the fields the user changed
 * from the value the form opened with: a changed field is set, a cleared one is
 * removed, stored nulls are dropped. `values` and `defaults` are the form values,
 * properties prefixed with `prop_`.
 */
export function mergeEditedProperties(
  existing: Record<string, any> | null | undefined,
  values: Record<string, any>,
  defaults: Record<string, any>,
): Record<string, any> {
  // A stored null/undefined is an empty value: the old dialog didn't send it either
  const merged: Record<string, any> = Object.fromEntries(
    Object.entries(existing || {}).filter(([, val]) => val !== null && val !== undefined),
  )
  for (const [key, val] of Object.entries(values)) {
    if (!key.startsWith(PROP_PREFIX) || val === defaults[key]) continue
    const name = key.slice(PROP_PREFIX.length)
    if (isEmpty(val)) {
      delete merged[name]
    } else {
      merged[name] = val
    }
  }
  return merged
}

/** Properties of a new asset: the non-empty `prop_` form values. */
export function newAssetProperties(values: Record<string, any>): Record<string, any> {
  const properties: Record<string, any> = {}
  for (const [key, val] of Object.entries(values)) {
    if (key.startsWith(PROP_PREFIX) && !isEmpty(val)) {
      properties[key.slice(PROP_PREFIX.length)] = val
    }
  }
  return properties
}
