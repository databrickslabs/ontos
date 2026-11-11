import { describe, it, expect } from 'vitest';
import { getOtherTypeName, getTargetTypeName } from './relationship-type';

describe('getTargetTypeName', () => {
  it('uses the local name of a "#" IRI, ignoring the display label', () => {
    expect(getTargetTypeName({
      target_type_iri: 'http://ontos.app/ontology#DataProduct',
      target_type_label: 'Data Product',
    })).toBe('DataProduct');
  });

  it('uses the local name of a "/" IRI', () => {
    expect(getTargetTypeName({
      target_type_iri: 'http://ontos.app/ontology/DataProduct',
      target_type_label: 'Data Product',
    })).toBe('DataProduct');
  });

  it('ignores a trailing "/" or "#" on the IRI', () => {
    expect(getTargetTypeName({
      target_type_iri: 'http://ontos.app/ontology/DataProduct/',
      target_type_label: 'Data Product',
    })).toBe('DataProduct');
    expect(getTargetTypeName({
      target_type_iri: 'http://ontos.app/ontology/DataProduct#',
      target_type_label: 'Data Product',
    })).toBe('DataProduct');
  });

  it('falls back to the label when the IRI is undefined or null', () => {
    expect(getTargetTypeName({ target_type_iri: undefined, target_type_label: 'Data Product' }))
      .toBe('DataProduct');
    expect(getTargetTypeName({ target_type_iri: null, target_type_label: 'Data Product' }))
      .toBe('DataProduct');
  });

  it('falls back to the label, with whitespace removed, when there is no IRI', () => {
    expect(getTargetTypeName({ target_type_iri: '', target_type_label: 'Data Product' }))
      .toBe('DataProduct');
  });

  it('returns an empty string when nothing is available', () => {
    expect(getTargetTypeName({ target_type_iri: '', target_type_label: null })).toBe('');
    expect(getTargetTypeName({ target_type_iri: '' })).toBe('');
  });
});

describe('getOtherTypeName', () => {
  // Shaped like GET /api/ontology/entity-types/relationships for a DataProduct.
  const outgoing = {
    direction: 'outgoing',
    source_type_iri: 'http://ontos.app/ontology#DataProduct',
    source_type_label: 'Data Product',
    target_type_iri: 'http://ontos.app/ontology#Dataset',
    target_type_label: 'Dataset',
  };
  const incoming = {
    direction: 'incoming',
    source_type_iri: 'http://ontos.app/ontology#DataDomain',
    source_type_label: 'Data Domain',
    target_type_iri: 'http://ontos.app/ontology#DataProduct',
    target_type_label: 'Data Product',
  };

  it('returns the target type of an outgoing definition', () => {
    expect(getOtherTypeName(outgoing)).toBe('Dataset');
  });

  it('returns the source type of an incoming definition', () => {
    expect(getOtherTypeName(incoming)).toBe('DataDomain');
  });

  it('falls back to the source label of an incoming definition without a source IRI', () => {
    expect(getOtherTypeName({ ...incoming, source_type_iri: '' })).toBe('DataDomain');
  });

  it('treats a missing direction as outgoing', () => {
    expect(getOtherTypeName({ ...outgoing, direction: undefined })).toBe('Dataset');
  });
});
