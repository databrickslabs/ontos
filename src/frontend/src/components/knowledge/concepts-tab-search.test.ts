import { describe, it, expect } from 'vitest';
import type { OntologyConcept } from '@/types/ontology';
import { matchConceptSearch } from './concepts-tab';

// ---------------------------------------------------------------------------
// matchConceptSearch: the single matcher shared by the list and tree views.
// Uses the REAL resolveLabel so language selection behaves as in the app.
// ---------------------------------------------------------------------------

const CUSTOMER = {
  iri: 'urn:ex:Customer',
  labels: { en: 'Customer', nl: 'Klant', de: 'Kunde' },
  comments: { en: 'A party that buys goods', nl: 'Een partij die goederen koopt' },
  synonyms: ['Client'],
  concept_type: 'concept',
  parent_concepts: [],
  child_concepts: [],
} as unknown as OntologyConcept;

describe('matchConceptSearch', () => {
  it('matches everything on an empty query', () => {
    expect(matchConceptSearch(CUSTOMER, '', 'en')).toEqual({ rank: 0 });
    expect(matchConceptSearch(CUSTOMER, '   ', 'en')).toEqual({ rank: 0 });
  });

  it('ranks exact < prefix < substring on the selected-language label', () => {
    expect(matchConceptSearch(CUSTOMER, 'customer', 'en')).toEqual({ rank: 0 });
    expect(matchConceptSearch(CUSTOMER, 'cust', 'en')).toEqual({ rank: 1 });
    expect(matchConceptSearch(CUSTOMER, 'tome', 'en')).toEqual({ rank: 2 });
  });

  it('matches another language label and reports that language', () => {
    expect(matchConceptSearch(CUSTOMER, 'klant', 'en')).toEqual({ rank: 3, viaLang: 'nl' });
    expect(matchConceptSearch(CUSTOMER, 'kunde', 'en')).toEqual({ rank: 3, viaLang: 'de' });
  });

  it('does not report a language hint when the selected language label matched', () => {
    expect(matchConceptSearch(CUSTOMER, 'klant', 'nl')).toEqual({ rank: 0 });
  });

  it('matches synonyms, any-language definitions and the IRI without a hint', () => {
    expect(matchConceptSearch(CUSTOMER, 'client', 'en')).toEqual({ rank: 3 });
    expect(matchConceptSearch(CUSTOMER, 'goederen', 'en')).toEqual({ rank: 3 });
    expect(matchConceptSearch(CUSTOMER, 'urn:ex', 'en')).toEqual({ rank: 3 });
  });

  it('returns null when nothing matches', () => {
    expect(matchConceptSearch(CUSTOMER, 'supplier', 'en')).toBeNull();
  });
});
