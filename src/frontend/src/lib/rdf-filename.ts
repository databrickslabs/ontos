/**
 * Frontend mirror of the backend `humanize_rdf_filename` helper in
 * `src/backend/src/utils/semantic_model_title_candidates.py`.
 *
 * Used to derive a human-readable label from an RDF source filename / slug
 * (for example `pizza.owl` -> `Pizza`, `gs1_taxonomy.skos` -> `GS1 Taxonomy`).
 *
 * Keep the algorithm in sync with the Python version when changing acronym
 * lists or extension lists.
 */

const RDF_FILE_EXTENSIONS: readonly string[] = [
  '.ttl',
  '.owl',
  '.rdf',
  '.xml',
  '.skos',
  '.rdfs',
  '.nt',
  '.n3',
  '.trig',
  '.trix',
  '.jsonld',
  '.json-ld',
  '.json',
];

const PRESERVED_CASE_TOKENS: ReadonlySet<string> = new Set([
  'FIBO', 'GS1', 'OWL', 'RDF', 'RDFS', 'SKOS', 'ODCS', 'ODPS',
  'W3C', 'OBO', 'GO', 'DCAT', 'PROV', 'SHACL', 'QUDT', 'FOAF',
  'DBpedia', 'DC', 'VOID', 'SIOC', 'OAI', 'ISO',
]);

function stripRdfExtension(name: string): string {
  const lower = name.toLowerCase();
  for (const ext of RDF_FILE_EXTENSIONS) {
    if (lower.endsWith(ext)) {
      return name.slice(0, name.length - ext.length);
    }
  }
  return name;
}

/**
 * Turn an RDF source filename / slug into a human-readable title.
 *
 * Steps mirror the backend:
 *   1. Take the basename (drop directory parts).
 *   2. Strip a single known RDF extension if present (case-insensitive).
 *   3. Replace `_`, `-`, `.` with spaces and collapse whitespace.
 *   4. Title-case word-by-word, preserving common acronyms (FIBO, GS1, ...).
 *
 * Returns the original input unchanged when cleaning would yield an empty
 * string so callers can fall back to the raw key.
 */
export function humanizeRdfFilename(filename: string): string {
  if (!filename) return '';

  const basename = filename.split(/[\\/]/).pop() ?? filename;
  const withoutExt = stripRdfExtension(basename);
  const cleaned = withoutExt.replace(/[._\-]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!cleaned) return filename;

  const parts = cleaned.split(' ').map((word) => {
    if (!word) return word;
    const upper = word.toUpperCase();
    if (PRESERVED_CASE_TOKENS.has(upper)) return upper;
    if (
      word === upper &&
      word.length <= 4 &&
      /^[A-Z]+$/.test(word)
    ) {
      return word;
    }
    return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
  });
  return parts.join(' ');
}
