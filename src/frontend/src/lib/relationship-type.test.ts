import { describe, it, expect } from 'vitest';
import { getTargetTypeName } from './relationship-type';

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
    expect(getTargetTypeName({ target_type_iri: undefined, target_type_label: 'Data Product' })).toBe('DataProduct');
    expect(getTargetTypeName({ target_type_iri: null, target_type_label: 'Data Product' })).toBe('DataProduct');
  });

  it('falls back to the label", with whitespace removed when there is no IRI', () => {
    expect(getTargetTypeName({ target_type_iri: '', target_type_label: 'Data Product' })).toBe('DataProduct');
  });

  it('returns an empty string when nothing is available', () => {
    expect(getTargetTypeName({ target_type_iri: '', target_type_label: null })).toBe('');
    expect(getTargetTypeName({ target_type_iri: '' })).toBe('');
  });
});
