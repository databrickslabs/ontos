import type { KnowledgeCollection } from '@/types/ontology';

// URN prefixes of the contexts a scheme's concepts live in. A scheme IRI minus its prefix is the
// scheme's source name, unless the backend says otherwise (see collectionSourceKey).
const SOURCE_PREFIXES = [
  'urn:glossary:',
  'urn:taxonomy:',
  'urn:ontology:',
  'urn:semantic-model:',
  'urn:schema:',
];

/** Scheme IRI without its URN type prefix, e.g. `urn:glossary:finance` -> `finance`. */
export function stripSourcePrefix(iri: string): string {
  for (const prefix of SOURCE_PREFIXES) {
    if (iri.startsWith(prefix)) {
      return iri.slice(prefix.length);
    }
  }
  return iri;
}

/**
 * The key a scheme's concepts are grouped under in `concepts-grouped`
 * (`source_context` on each concept). The backend sends it as `source_key`; it differs from the
 * stripped IRI for contexts with a fixed group name (for example the demo scheme `urn:demo`
 * is grouped as "Demo Data"). Falls back to the stripped IRI for older responses.
 */
export function collectionSourceKey(
  collection: Pick<KnowledgeCollection, 'iri'> & { source_key?: string | null },
): string {
  return collection.source_key || stripSourcePrefix(collection.iri);
}
