import { describe, it, expect } from 'vitest';
import { toReferenceSlug } from './compliance-reference-id';

describe('toReferenceSlug', () => {
  it.each([
    ['Limitações conhecidas', 'limitacoes-conhecidas'],
    ['Área Responsável', 'area-responsavel'],
    ['Über die Daten', 'uber-die-daten'],
    ['Niño & Ñandú', 'nino-nandu'],
    ['Crème brûlée', 'creme-brulee'],
    ['  Owner (team)  ', 'owner-team'],
    ['already-a-slug_1', 'already-a-slug-1'],
  ])('%s -> %s', (input, expected) => {
    expect(toReferenceSlug(input)).toBe(expected);
  });

  it('returns an empty string when nothing is left (callers fall back to field-N)', () => {
    expect(toReferenceSlug('データ')).toBe('');
    expect(toReferenceSlug('---')).toBe('');
  });

  it('matches the backend reference id rule', () => {
    expect(toReferenceSlug('Ação de Correção 2')).toMatch(/^[a-z0-9][a-z0-9_-]*$/);
  });
});
