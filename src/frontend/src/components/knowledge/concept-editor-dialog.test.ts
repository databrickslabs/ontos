import { describe, it, expect } from 'vitest';
import { allowedConceptTypes } from './concept-editor-dialog';

// Type selector options are restricted by the target collection's type.
describe('allowedConceptTypes', () => {
  it('glossary allows concept and term', () => {
    expect(allowedConceptTypes('glossary')).toEqual(['concept', 'term']);
  });

  it('taxonomy allows only concept', () => {
    expect(allowedConceptTypes('taxonomy')).toEqual(['concept']);
  });

  it('ontology allows concept, class, property, individual', () => {
    expect(allowedConceptTypes('ontology')).toEqual(['concept', 'class', 'property', 'individual']);
  });

  it('unknown or missing collection type allows all five', () => {
    const all = ['concept', 'class', 'property', 'individual', 'term'];
    expect(allowedConceptTypes(undefined)).toEqual(all);
    expect(allowedConceptTypes(null)).toEqual(all);
    expect(allowedConceptTypes('something-else')).toEqual(all);
  });

  it('every collection type allows concept (the reset fallback)', () => {
    for (const ct of ['glossary', 'taxonomy', 'ontology']) {
      expect(allowedConceptTypes(ct)).toContain('concept');
    }
  });
});
