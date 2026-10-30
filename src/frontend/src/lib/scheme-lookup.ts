import type { KnowledgeCollection } from '@/types/ontology';
import { collectionSourceKey } from '@/lib/collection-source-key';

/**
 * Every scheme of a (possibly nested) collections list, parents before their
 * children. The collections endpoint returns a nested tree when asked for
 * `hierarchical=true` and a flat list otherwise; both flatten the same way.
 */
export function flattenCollectionTree(
  collections: KnowledgeCollection[] | null | undefined,
): KnowledgeCollection[] {
  const out: KnowledgeCollection[] = [];
  const walk = (nodes: KnowledgeCollection[] | null | undefined) => {
    for (const c of nodes ?? []) {
      out.push(c);
      walk(c.child_collections);
    }
  };
  walk(collections);
  return out;
}

/**
 * Builds a lookup from the key a scheme's concepts are grouped under
 * (`source_context`, sent by the backend as `source_key`) to the scheme record.
 * The record carries the current label, so a rename shows up wherever the
 * lookup is used. Matching is exact: the first scheme wins on a duplicate key,
 * and a scheme IRI is accepted as a fallback key.
 */
export function createSchemeLookup(
  collections: KnowledgeCollection[] | null | undefined,
): (sourceKey?: string | null) => KnowledgeCollection | null {
  const flat = flattenCollectionTree(collections);
  const byKey = new Map<string, KnowledgeCollection>();
  for (const c of flat) {
    const key = collectionSourceKey(c);
    if (!byKey.has(key)) byKey.set(key, c);
  }
  return (sourceKey) => {
    if (!sourceKey) return null;
    return byKey.get(sourceKey) ?? flat.find((c) => c.iri === sourceKey) ?? null;
  };
}
