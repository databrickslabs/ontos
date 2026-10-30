import { describe, it, expect } from 'vitest';
import { buildKgSearchParams, DEFAULT_KG_SPARQL } from './kg-search-url';

const base = { prefix: '', path: [], sparql: DEFAULT_KG_SPARQL, directionFilter: 'all', showConceptsOnly: false };

describe('buildKgSearchParams', () => {
  it('keeps the host page params (view, source, concept)', () => {
    const p = buildKgSearchParams('?view=graph&source=my-scheme&concept=urn%3Aa', { ...base, prefix: 'pump' });
    expect(p.get('view')).toBe('graph');
    expect(p.get('source')).toBe('my-scheme');
    expect(p.get('concept')).toBe('urn:a');
    expect(p.get('prefix')).toBe('pump');
    expect(p.get('tab')).toBe('kg');
  });

  it('replaces the search keys and drops defaults', () => {
    const p = buildKgSearchParams('?prefix=old&path=a|b&sparql=SELECT%201&direction=incoming&concepts_only=true&view=list', base);
    expect(p.has('prefix')).toBe(false);
    expect(p.has('path')).toBe(false);
    expect(p.has('sparql')).toBe(false);
    expect(p.has('direction')).toBe(false);
    expect(p.has('concepts_only')).toBe(false);
    expect(p.get('view')).toBe('list');
  });

  it('writes non-default state', () => {
    const p = buildKgSearchParams('', { prefix: 'x', path: ['a', 'b'], sparql: 'SELECT 1', directionFilter: 'outgoing', showConceptsOnly: true });
    expect(p.get('path')).toBe('a|b');
    expect(p.get('sparql')).toBe('SELECT 1');
    expect(p.get('direction')).toBe('outgoing');
    expect(p.get('concepts_only')).toBe('true');
  });
});
