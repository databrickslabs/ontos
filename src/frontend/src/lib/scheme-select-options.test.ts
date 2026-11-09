import { describe, it, expect } from 'vitest';
import type { KnowledgeCollection } from '@/types/ontology';
import { buildSchemeOptionGroups, flattenSchemeTree } from './scheme-select-options';

const make = (overrides: Partial<KnowledgeCollection>): KnowledgeCollection => ({
  iri: 'urn:scheme:x',
  label: 'X',
  collection_type: 'glossary',
  scope_level: 'enterprise',
  source_type: 'custom',
  is_editable: true,
  status: 'active',
  concept_count: 0,
  child_collections: [],
  ...overrides,
});

describe('flattenSchemeTree', () => {
  it('walks the nested tree depth first', () => {
    const tree = [
      make({ iri: 'a', child_collections: [make({ iri: 'a1', child_collections: [make({ iri: 'a11' })] })] }),
      make({ iri: 'b' }),
    ];
    expect(flattenSchemeTree(tree).map((c) => c.iri)).toEqual(['a', 'a1', 'a11', 'b']);
  });
});

describe('buildSchemeOptionGroups', () => {
  it('returns no groups for empty input', () => {
    expect(buildSchemeOptionGroups([])).toEqual([]);
  });

  it('orders groups glossary, taxonomy, ontology and omits empty groups', () => {
    const groups = buildSchemeOptionGroups([
      make({ iri: 'o', label: 'Onto', collection_type: 'ontology' }),
      make({ iri: 'g', label: 'Gloss', collection_type: 'glossary' }),
    ]);
    expect(groups.map((g) => g.type)).toEqual(['glossary', 'ontology']);

    const all = buildSchemeOptionGroups([
      make({ iri: 'o', collection_type: 'ontology' }),
      make({ iri: 't', collection_type: 'taxonomy' }),
      make({ iri: 'g', collection_type: 'glossary' }),
    ]);
    expect(all.map((g) => g.type)).toEqual(['glossary', 'taxonomy', 'ontology']);
  });

  it('sorts options alphabetically, case-insensitive', () => {
    const [group] = buildSchemeOptionGroups([
      make({ iri: '1', label: 'zeta' }),
      make({ iri: '2', label: 'Beta' }),
      make({ iri: '3', label: 'alpha' }),
    ]);
    expect(group.options.map((o) => o.label)).toEqual(['alpha', 'Beta', 'zeta']);
  });

  it('lists an editable child of a read-only parent, flat, with the parent label', () => {
    const tree = [
      make({
        iri: 'parent',
        label: 'Bundled Parent',
        is_editable: false,
        child_collections: [
          make({ iri: 'child', label: 'Child', parent_collection_iri: 'parent' }),
        ],
      }),
    ];
    const groups = buildSchemeOptionGroups(tree);
    expect(groups).toEqual([
      { type: 'glossary', options: [{ iri: 'child', label: 'Child', parentLabel: 'Bundled Parent' }] },
    ]);
    expect(groups[0].options[0]).not.toHaveProperty('level');
  });

  it('leaves parentLabel undefined for roots and unknown parents', () => {
    const [group] = buildSchemeOptionGroups([
      make({ iri: 'root', label: 'Root' }),
      make({ iri: 'orphan', label: 'Orphan', parent_collection_iri: 'urn:missing' }),
    ]);
    expect(group.options.every((o) => o.parentLabel === undefined)).toBe(true);
  });

  it('honours an include override', () => {
    const tree = [
      make({ iri: 'a', label: 'A', is_editable: false }),
      make({ iri: 'b', label: 'B' }),
    ];
    const [group] = buildSchemeOptionGroups(tree, { include: (c) => c.iri === 'a' });
    expect(group.options.map((o) => o.iri)).toEqual(['a']);
  });

  it('puts an unexpected type into a trailing group keyed by its value', () => {
    const groups = buildSchemeOptionGroups([
      make({ iri: 'x', label: 'Custom', collection_type: 'vocabulary' as never }),
      make({ iri: 'g', label: 'Gloss', collection_type: 'glossary' }),
    ]);
    expect(groups.map((g) => g.type)).toEqual(['glossary', 'vocabulary']);
    expect(groups[1].options[0].iri).toBe('x');
  });
});
