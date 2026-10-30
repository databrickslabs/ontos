import { describe, it, expect } from 'vitest';
import type { KnowledgeCollection } from '@/types/ontology';
import { createSchemeLookup, flattenCollectionTree } from './scheme-lookup';

const mk = (iri: string, label: string, extra: Partial<KnowledgeCollection> = {}): KnowledgeCollection => ({
  iri,
  label,
  collection_type: 'glossary',
  scope_level: 'enterprise',
  source_type: 'custom',
  is_editable: true,
  status: 'active',
  concept_count: 0,
  child_collections: [],
  ...extra,
});

describe('flattenCollectionTree', () => {
  it('returns parents before children for a nested tree', () => {
    const child = mk('urn:glossary:risk', 'Risk');
    const parent = mk('urn:glossary:enterprise', 'Enterprise', { child_collections: [child] });
    expect(flattenCollectionTree([parent]).map((c) => c.label)).toEqual(['Enterprise', 'Risk']);
  });

  it('accepts a flat list, null and undefined', () => {
    expect(flattenCollectionTree([mk('urn:glossary:a', 'A'), mk('urn:glossary:b', 'B')])).toHaveLength(2);
    expect(flattenCollectionTree(null)).toEqual([]);
    expect(flattenCollectionTree(undefined)).toEqual([]);
  });
});

describe('createSchemeLookup', () => {
  it('finds a scheme by the key its concepts are grouped under', () => {
    const find = createSchemeLookup([mk('urn:glossary:finance', 'Finance')]);
    expect(find('finance')?.label).toBe('Finance');
  });

  it('prefers the backend source_key over the stripped IRI', () => {
    const demo = mk('urn:demo', 'Demo Business Concepts', { source_key: 'Demo Data' });
    const find = createSchemeLookup([demo]);
    expect(find('Demo Data')?.label).toBe('Demo Business Concepts');
    expect(find('demo')).toBeNull();
  });

  it('finds a nested child scheme', () => {
    const child = mk('urn:glossary:risk', 'Risk & Compliance Glossary');
    const parent = mk('urn:glossary:enterprise', 'Enterprise', { child_collections: [child] });
    expect(createSchemeLookup([parent])('risk')?.label).toBe('Risk & Compliance Glossary');
  });

  it('returns the current label after a rename', () => {
    const before = createSchemeLookup([mk('urn:ontology:supply-chain', 'Supply Chain Ontology')]);
    const after = createSchemeLookup([mk('urn:ontology:supply-chain', 'Supply Chain Ontology TEST')]);
    expect(before('supply-chain')?.label).toBe('Supply Chain Ontology');
    expect(after('supply-chain')?.label).toBe('Supply Chain Ontology TEST');
  });

  it('matches exactly: a key that only shares a suffix does not match', () => {
    const find = createSchemeLookup([mk('urn:glossary:xfoo', 'Not Foo')]);
    expect(find('foo')).toBeNull();
  });

  it('falls back to an exact scheme IRI', () => {
    const find = createSchemeLookup([mk('urn:glossary:finance', 'Finance')]);
    expect(find('urn:glossary:finance')?.label).toBe('Finance');
  });

  it('keeps the first scheme on a duplicate key', () => {
    const find = createSchemeLookup([mk('urn:glossary:dup', 'First'), mk('urn:taxonomy:dup', 'Second')]);
    expect(find('dup')?.label).toBe('First');
  });

  it('returns null for an empty key or an unknown scheme', () => {
    const find = createSchemeLookup([mk('urn:glossary:finance', 'Finance')]);
    expect(find(undefined)).toBeNull();
    expect(find('')).toBeNull();
    expect(find('nope')).toBeNull();
  });
});
