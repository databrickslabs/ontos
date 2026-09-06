import { describe, expect, it } from 'vitest';

import { humanizeRdfFilename } from './rdf-filename';

/**
 * Parity tests for the backend `humanize_rdf_filename` helper.
 *
 * Keep in lockstep with
 * `src/backend/src/tests/unit/test_semantic_model_title_candidates.py`.
 */
describe('humanizeRdfFilename', () => {
  const cases: Array<[string, string]> = [
    ['pizza.owl', 'Pizza'],
    ['PIZZA.OWL', 'Pizza'],
    ['my_ontology.ttl', 'My Ontology'],
    ['my-ontology-v2.ttl', 'My Ontology V2'],
    ['databricks_ontology.ttl', 'Databricks Ontology'],
    ['fibo-quick-fix.rdf', 'FIBO Quick Fix'],
    ['gs1_taxonomy.skos', 'GS1 Taxonomy'],
    ['Schema.org.jsonld', 'Schema Org'],
    ['foo.bar.baz.owl', 'Foo Bar Baz'],
    ['/tmp/uploads/some_file.rdfs', 'Some File'],
    ['nodot', 'Nodot'],
    ['ALLCAPS.TTL', 'Allcaps'],
    ['abc.TTL', 'Abc'],
    ['odcs-ontology', 'ODCS Ontology'],
    ['ontos-ontology', 'Ontos Ontology'],
  ];

  it.each(cases)('humanizes %s -> %s', (input, expected) => {
    expect(humanizeRdfFilename(input)).toBe(expected);
  });

  it('returns empty string when input is empty', () => {
    expect(humanizeRdfFilename('')).toBe('');
  });

  it('title-cases a short all-caps-looking token that contains a digit', () => {
    // 'API2' is <=4 chars and upper-cased, but /^[A-Z]+$/ fails on the digit,
    // so it is NOT preserved as an acronym and falls through to title case.
    expect(humanizeRdfFilename('api2.owl')).toBe('Api2');
  });

  it('preserves a short pure-uppercase token that is not in the acronym set', () => {
    // 'XYZ' is <=4, all letters, all caps -> preserved verbatim (not in
    // PRESERVED_CASE_TOKENS, but the generic short-all-caps rule keeps it).
    expect(humanizeRdfFilename('XYZ.ttl')).toBe('XYZ');
  });

  it('returns input unchanged when cleaning would yield empty', () => {
    // Stripping the only RDF extension leaves no name to humanize, so we
    // fall back to the raw input so callers can gracefully handle it.
    expect(humanizeRdfFilename('.ttl')).toBe('.ttl');
  });
});
