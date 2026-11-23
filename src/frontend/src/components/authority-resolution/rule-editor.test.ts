import { describe, expect, it } from 'vitest';
import { emptyItem, itemsFromRule, ruleFromItems } from './rule-editor';
import { paramRowsFrom, scopeRowsFrom, toDomainContext } from './domain-context-editor';
import type { ArfRule } from '@/types/authority-resolution';

const RULE: ArfRule = {
  permission: {
    constraint: [
      { leftOperand: 'payAmount', operator: 'lteq', rightOperandReference: 'ctx.threshold', message: 'Too high', direction: 'actual-exceeds-documented', weight: 1, dimension: 'policy' },
    ],
    duty: [{
      action: 'arf:obtainCoApproval', name: 'VP sign-off', direction: 'documented-exceeds-actual', weight: 1, dimension: 'policy',
      constraint: [{ or: [
        { leftOperand: 'arf:budget_usd', operator: 'lteq', rightOperandReference: 'ctx.threshold_usd' },
        { leftOperand: 'arf:has_vp_sign_off', operator: 'eq', rightOperand: true },
      ] }],
    }],
  },
  prohibition: [{
    message: 'No self-grant', direction: 'actual-exceeds-documented', weight: 1, dimension: 'people',
    constraint: [{ leftOperand: 'arf:grantee', operator: 'eq', rightOperandReference: 'req.actor_identity' }],
  }],
};

describe('rule editor serialization', () => {
  it('round-trips a rule with constraints, an any-of duty and a prohibition', () => {
    expect(ruleFromItems(itemsFromRule(RULE))).toEqual(RULE);
  });

  it('coerces literals by operand kind and splits lists', () => {
    const item = emptyItem('constraint');
    item.parts = [
      { operand: 'payAmount', customKey: '', operator: 'lteq', ref: '', value: '0.15' },
      { operand: 'arf:cosignPresent', customKey: '', operator: 'eq', ref: '', value: 'true' },
      { operand: '__custom__', customKey: 'market', operator: 'isAnyOf', ref: '', value: 'DE, AT' },
    ];
    item.join = 'and';
    const rule = ruleFromItems([item]);
    expect(rule?.permission?.constraint?.[0]).toMatchObject({
      and: [
        { leftOperand: 'payAmount', operator: 'lteq', rightOperand: 0.15 },
        { leftOperand: 'arf:cosignPresent', operator: 'eq', rightOperand: true },
        { leftOperand: 'arf:market', operator: 'isAnyOf', rightOperand: ['DE', 'AT'] },
      ],
    });
  });

  it('returns null when nothing is authored', () => {
    expect(ruleFromItems([])).toBeNull();
  });

  it('keeps nested logic it cannot edit as JSON', () => {
    const nested: ArfRule = { permission: { duty: [{ action: 'arf:x', constraint: [
      { or: [{ and: [{ leftOperand: 'payAmount', operator: 'lt', rightOperand: 1 }, { leftOperand: 'arf:escalated', operator: 'eq', rightOperand: true }] } as any,
             { leftOperand: 'arf:cosignPresent', operator: 'eq', rightOperand: true }] },
    ] }] } };
    const items = itemsFromRule(nested);
    expect(items[0].rawJson).toBeTruthy();
    expect(ruleFromItems(items)?.permission?.duty?.[0].constraint).toEqual(nested.permission!.duty![0].constraint);
  });
});

describe('domain context editor', () => {
  it('builds eq / isAnyOf scope constraints and typed params', () => {
    const out = toDomainContext(
      [{ key: 'market', match: 'in', values: 'DE, AT' }, { key: 'channel', match: 'in', values: 'modern-trade' }],
      [{ key: 'threshold', type: 'number', value: '0.15' }, { key: 'cleared', type: 'list', value: 'DE,AT' },
       { key: 'strict', type: 'boolean', value: 'false' }],
    );
    expect(out.value).toEqual({
      scope: [
        { leftOperand: 'arf:market', operator: 'isAnyOf', rightOperand: ['DE', 'AT'] },
        { leftOperand: 'arf:channel', operator: 'eq', rightOperand: 'modern-trade' },
      ],
      params: { threshold: 0.15, cleared: ['DE', 'AT'], strict: false },
    });
    expect(scopeRowsFrom(out.value)[0]).toEqual({ key: 'market', match: 'in', values: 'DE, AT' });
    expect(paramRowsFrom(out.value).map((p) => p.type)).toEqual(['number', 'list', 'boolean']);
  });

  it('reports invalid keys and numbers', () => {
    expect(toDomainContext([{ key: 'bad key', match: 'in', values: 'x' }], []).error?.key).toBe('domainContext.validation.invalidKey');
    expect(toDomainContext([], [{ key: 'n', type: 'number', value: 'abc' }]).error?.key).toBe('domainContext.validation.notANumber');
    expect(toDomainContext([{ key: 'market', match: 'in', values: '' }], []).error?.key).toBe('domainContext.validation.missingValue');
  });
});

describe('domain context params round-trip', () => {
  it('keeps object and mixed-list params as JSON', () => {
    const dc = { scope: [], params: { limits: { eur: 100 }, tiers: [1, 2], none: null } };
    const out = toDomainContext([], paramRowsFrom(dc as any));
    expect(out.value?.params).toEqual(dc.params);
  });
});
