/**
 * Where the Add Relationship dialog finds the entities a relationship can point to.
 *
 * Asset-backed targets ("Table", "Logical Attribute") come from the assets API. Domains,
 * products, contracts, teams, projects and ontology concepts aren't assets: they come
 * from `GET /api/suggestions/link-candidates`. "Asset", the superclass of every asset
 * type, accepts any asset. Other targets (ownership, reviews, output ports) are managed
 * on their own pages and can't be picked here.
 */
export type RelationshipTargetSource =
  | { kind: 'asset'; assetTypeNames: string[] | null }
  | { kind: 'candidates' }
  | { kind: 'unsupported' };

export const CANDIDATE_TARGET_TYPES = new Set([
  'DataDomain',
  'DataProduct',
  'DataContract',
  'Team',
  'Project',
  'OntologyConcept',
]);

export const GENERIC_ASSET_TARGET = 'Asset';

/** "Logical Entity" -> "LogicalEntity": asset type names are the classes' labels. */
export function assetTypeLocalName(name: string): string {
  return name.replace(/\s+/g, '');
}

/**
 * @param targetTypeName machine type name of the relationship's target (`getTargetTypeName`)
 * @param assetTypeNames names of the active asset types
 */
export function relationshipTargetSource(
  targetTypeName: string,
  assetTypeNames: string[],
): RelationshipTargetSource {
  if (CANDIDATE_TARGET_TYPES.has(targetTypeName)) return { kind: 'candidates' };
  if (targetTypeName === GENERIC_ASSET_TARGET) return { kind: 'asset', assetTypeNames: null };
  const matches = assetTypeNames.filter(name => assetTypeLocalName(name) === targetTypeName);
  if (matches.length > 0) return { kind: 'asset', assetTypeNames: matches };
  return { kind: 'unsupported' };
}
