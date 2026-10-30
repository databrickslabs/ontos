import { describe, it, expect } from 'vitest';
import { schemeKindsForType } from './concept-editor-dialog';

// The fixed entry type decides which scheme kinds the editor offers.
describe('schemeKindsForType', () => {
  it('term lives in glossaries', () => {
    expect(schemeKindsForType('term')).toEqual(['glossary']);
  });

  it('concept lives in taxonomies', () => {
    expect(schemeKindsForType('concept')).toEqual(['taxonomy']);
  });

  it('class, individual and property live in ontologies', () => {
    expect(schemeKindsForType('class')).toEqual(['ontology']);
    expect(schemeKindsForType('individual')).toEqual(['ontology']);
    expect(schemeKindsForType('property')).toEqual(['ontology']);
  });
});
