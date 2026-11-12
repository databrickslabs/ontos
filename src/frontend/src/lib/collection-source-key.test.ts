import { describe, it, expect } from 'vitest';
import { collectionSourceKey, stripSourcePrefix } from './collection-source-key';

describe('stripSourcePrefix', () => {
  it('removes known URN type prefixes', () => {
    expect(stripSourcePrefix('urn:glossary:finance')).toBe('finance');
    expect(stripSourcePrefix('urn:taxonomy:geo')).toBe('geo');
    expect(stripSourcePrefix('urn:ontology:core')).toBe('core');
    expect(stripSourcePrefix('urn:semantic-model:sales')).toBe('sales');
    expect(stripSourcePrefix('urn:schema:orders')).toBe('orders');
  });

  it('returns other IRIs unchanged', () => {
    expect(stripSourcePrefix('urn:demo')).toBe('urn:demo');
    expect(stripSourcePrefix('http://example.org/x')).toBe('http://example.org/x');
  });
});

describe('collectionSourceKey', () => {
  it('prefers the backend source_key', () => {
    expect(collectionSourceKey({ iri: 'urn:demo', source_key: 'Demo Data' })).toBe('Demo Data');
  });

  it('falls back to the stripped IRI when source_key is missing or empty', () => {
    expect(collectionSourceKey({ iri: 'urn:glossary:finance' })).toBe('finance');
    expect(collectionSourceKey({ iri: 'urn:glossary:finance', source_key: null })).toBe('finance');
    expect(collectionSourceKey({ iri: 'urn:glossary:finance', source_key: '' })).toBe('finance');
  });
});
