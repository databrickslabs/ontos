import type { CollectionType, KnowledgeCollection } from '@/types/ontology';

/** One selectable scheme in a target/parent scheme dropdown. */
export interface SchemeOption {
  iri: string;
  label: string;
  /** Label of the scheme this one is nested under, when it has a known parent. */
  parentLabel?: string;
}

/**
 * Options of one scheme type. Known types come first in a fixed order; any
 * unexpected type value gets its own trailing group keyed by that value.
 */
export interface SchemeOptionGroup {
  type: CollectionType | (string & {});
  options: SchemeOption[];
}

const GROUP_ORDER: CollectionType[] = ['glossary', 'taxonomy', 'ontology'];

/** Depth-first flatten of the nested scheme tree (children in `child_collections`). */
export function flattenSchemeTree(collections: KnowledgeCollection[]): KnowledgeCollection[] {
  const out: KnowledgeCollection[] = [];
  const walk = (colls: KnowledgeCollection[] | undefined) => {
    for (const c of colls ?? []) {
      out.push(c);
      walk(c.child_collections);
    }
  };
  walk(collections);
  return out;
}

/**
 * Build grouped, alphabetically sorted dropdown options from the nested scheme
 * tree. Every scheme is judged on its own merit by `include` (default: editable),
 * so an included child under an excluded parent is still offered. Hierarchy is
 * shown through `parentLabel` instead of indentation.
 */
export function buildSchemeOptionGroups(
  collections: KnowledgeCollection[],
  opts?: { include?: (c: KnowledgeCollection) => boolean },
): SchemeOptionGroup[] {
  const include = opts?.include ?? ((c: KnowledgeCollection) => c.is_editable);
  const all = flattenSchemeTree(collections);
  const labelByIri = new Map(all.map((c) => [c.iri, c.label] as const));

  const byType = new Map<string, SchemeOption[]>();
  for (const c of all) {
    if (!include(c)) continue;
    const parentLabel = c.parent_collection_iri
      ? labelByIri.get(c.parent_collection_iri)
      : undefined;
    const option: SchemeOption = { iri: c.iri, label: c.label };
    if (parentLabel !== undefined) option.parentLabel = parentLabel;
    const key = String(c.collection_type);
    const list = byType.get(key);
    if (list) list.push(option);
    else byType.set(key, [option]);
  }

  const known = GROUP_ORDER.filter((t) => byType.has(t));
  const unknown = [...byType.keys()].filter(
    (t) => !(GROUP_ORDER as string[]).includes(t),
  );
  return [...known, ...unknown].map((type) => ({
    type,
    options: [...byType.get(type)!].sort((a, b) =>
      a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }),
    ),
  }));
}
