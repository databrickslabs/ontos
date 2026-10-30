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

/**
 * Machine type name of the end of a relationship definition that is not the
 * current entity. `GET /api/ontology/entity-types/relationships` puts the
 * current type in `source_type_*` for outgoing definitions and in
 * `target_type_*` for incoming ones, so the other end is the target of an
 * outgoing definition and the source of an incoming one.
 */
export function getOtherTypeName(rel: {
  direction?: string | null;
  source_type_iri?: string | null;
  source_type_label?: string | null;
  target_type_iri?: string | null;
  target_type_label?: string | null;
}): string {
  if (rel.direction !== 'incoming') return getTargetTypeName(rel);
  return getTargetTypeName({
    target_type_iri: rel.source_type_iri,
    target_type_label: rel.source_type_label,
  });
}
