import { describe, expect, it } from 'vitest';
import { operandForKey, scopeKey, scopeRequestKeys } from './authority-resolution';

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
