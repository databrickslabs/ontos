/**
 * Machine type name (IRI local name, e.g. "DataProduct") of a relationship's
 * target type. Use this wherever a type name is sent to the API or used as a
 * lookup key; `target_type_label` is the human-readable rdfs:label
 * ("Data Product") and is for display only.
 */
export function getTargetTypeName(
  rel: { target_type_iri?: string | null; target_type_label?: string | null },
): string {
  const segments = (rel.target_type_iri ?? '').split(/[#/]/).filter(Boolean);
  const localName = segments[segments.length - 1];
  if (localName) return localName;
  return (rel.target_type_label ?? '').replace(/\s+/g, '');
}
