import { describe, expect, it } from 'vitest';
import {
  ADM_SCHEMA_PATTERN, ACTION_CODE_PATTERN, dnaDimensionRows, draftFromEvidenceSlice, evidenceSliceErrors,
  evidenceSliceFromDraft, isLegacyDnaDimensions, newEvidenceSliceDraft, operandForKey, scopeKey, scopeRequestKeys,
  type EvidenceSliceDraft,
} from './authority-resolution';

// The request field a scope operand reads must match the backend's scope_key (#1491-2):
// a typed field prefills its canonical field, not the bare key the author typed.
describe('scope request keys', () => {
  it('maps typed fields to their canonical request field', () => {
    expect(scopeKey('arf:actor')).toBe('actor_identity');
    expect(scopeKey('arf:objectId')).toBe('object_id');
    expect(scopeKey('payAmount')).toBe('value');
  });

  it('keeps a plain profile key and an ODRL context operand as they are', () => {
    expect(scopeKey('arf:market')).toBe('market');
    expect(scopeKey('spatial')).toBe('spatial');
  });

  it('prefills from an authoring key the way the dialog stores it', () => {
    expect(scopeKey(operandForKey(' actor '))).toBe('actor_identity');
    expect(scopeKey(operandForKey('market'))).toBe('market');
  });

  it('lists the request fields of stored scope operands', () => {
    expect(scopeRequestKeys([
      { leftOperand: 'arf:actor' }, { leftOperand: 'arf:market' },
    ])).toEqual(['actor_identity', 'market']);
  });
});

// The evidence slice keeps the server bounds (#1294 slice 4): 1..20 action codes, up to 200
// object refs, a window of 1..3650 days and a sample of 1..5000.
describe('evidence slice', () => {
  const valid = (over: Partial<EvidenceSliceDraft> = {}): EvidenceSliceDraft => ({
    ...newEvidenceSliceDraft(), ...over,
  });

  it('accepts the default slice', () => {
    expect(evidenceSliceErrors(newEvidenceSliceDraft())).toEqual([]);
    expect(newEvidenceSliceDraft().action_codes).toEqual(['approve']);
  });

  it('requires at least one action code and at most 20', () => {
    expect(evidenceSliceErrors(valid({ action_codes: [] }))).toEqual(['actionCodesRequired']);
    expect(evidenceSliceErrors(valid({ action_codes: Array.from({ length: 21 }, (_, i) => `code${i}`) })))
      .toEqual(['actionCodesTooMany']);
  });

  it('accepts lowercase action codes only', () => {
    expect(ACTION_CODE_PATTERN.test('approve')).toBe(true);
    expect(ACTION_CODE_PATTERN.test('no-escalate_2')).toBe(true);
    expect(ACTION_CODE_PATTERN.test('Approve')).toBe(false);
    expect(ACTION_CODE_PATTERN.test('2fa')).toBe(false);
    expect(ACTION_CODE_PATTERN.test('bad code')).toBe(false);
    expect(evidenceSliceErrors(valid({ action_codes: ['Approve'] }))).toEqual(['actionCodeInvalid']);
  });

  it('caps object refs at 200', () => {
    expect(evidenceSliceErrors(valid({ object_refs: Array.from({ length: 200 }, (_, i) => `o${i}`) }))).toEqual([]);
    expect(evidenceSliceErrors(valid({ object_refs: Array.from({ length: 201 }, (_, i) => `o${i}`) })))
      .toEqual(['objectRefsTooMany']);
  });

  it('keeps the window within 1 to 3650 whole days and the sample within 1 to 5000', () => {
    expect(evidenceSliceErrors(valid({ window_days: '1', sample_size: '5000' }))).toEqual([]);
    expect(evidenceSliceErrors(valid({ window_days: '3650' }))).toEqual([]);
    expect(evidenceSliceErrors(valid({ window_days: '0' }))).toEqual(['windowDaysRange']);
    expect(evidenceSliceErrors(valid({ window_days: '3651' }))).toEqual(['windowDaysRange']);
    expect(evidenceSliceErrors(valid({ window_days: '2.5' }))).toEqual(['windowDaysRange']);
    expect(evidenceSliceErrors(valid({ window_days: '' }))).toEqual(['windowDaysRange']);
    expect(evidenceSliceErrors(valid({ sample_size: '5001' }))).toEqual(['sampleSizeRange']);
    expect(evidenceSliceErrors(valid({ sample_size: 'abc' }))).toEqual(['sampleSizeRange']);
  });

  it('converts a valid draft to the wire shape and back', () => {
    const slice = evidenceSliceFromDraft(valid({ window_days: ' 30 ', sample_size: '200', domain_scope: false, object_refs: ['o1'] }));
    expect(slice).toEqual({ action_codes: ['approve'], object_refs: ['o1'], domain_scope: false, window_days: 30, sample_size: 200 });
    expect(draftFromEvidenceSlice(slice)).toEqual({
      action_codes: ['approve'], object_refs: ['o1'], domain_scope: false, window_days: '30', sample_size: '200',
    });
  });

  it('checks the catalog.schema shape of an ADM schema override', () => {
    expect(ADM_SCHEMA_PATTERN.test('demo.arf_adm')).toBe(true);
    expect(ADM_SCHEMA_PATTERN.test('demo')).toBe(false);
    expect(ADM_SCHEMA_PATTERN.test('demo.arf adm')).toBe(false);
    expect(ADM_SCHEMA_PATTERN.test('a.b.c')).toBe(false);
  });
});

describe('DNA dimensions', () => {
  it('reads a new entry as a signed position with its magnitude and weight', () => {
    expect(dnaDimensionRows({ people: { position: -0.5, magnitude: 0.2, weight: 1 } })).toEqual([
      { name: 'people', position: -0.5, magnitude: 0.2, weight: 1, definition: false, legacy: false },
    ]);
  });

  it('marks the structural entry as a definition and keeps rows sorted by name', () => {
    const rows = dnaDimensionRows({
      structural: { position: 0, magnitude: 0.6, weight: 0.5, kind: 'definition' },
      people: { position: 0.1, magnitude: 0.1, weight: 1 },
    });
    expect(rows.map((r) => r.name)).toEqual(['people', 'structural']);
    expect(rows[1].definition).toBe(true);
  });

  it('reads a legacy bare number as a magnitude with no signed position', () => {
    const rows = dnaDimensionRows({ people: 0.15 });
    expect(rows).toEqual([{ name: 'people', position: null, magnitude: 0.15, weight: null, definition: false, legacy: true }]);
    expect(isLegacyDnaDimensions({ people: 0.15 })).toBe(true);
    expect(isLegacyDnaDimensions({ people: { position: 0.1, magnitude: 0.1, weight: 1 } })).toBe(false);
  });

  it('clamps out-of-range values into their ranges and tolerates no dimensions', () => {
    expect(dnaDimensionRows({ a: { position: 3, magnitude: -1, weight: 1 } })[0]).toMatchObject({ position: 1, magnitude: 0 });
    expect(dnaDimensionRows(null)).toEqual([]);
    expect(isLegacyDnaDimensions(undefined)).toBe(false);
  });
});

