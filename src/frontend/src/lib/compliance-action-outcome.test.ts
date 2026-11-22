import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';
import {
  complianceActionError,
  complianceActionLabel,
  complianceActionOutcomes,
} from './compliance-action-outcome';

// Echoes the key and the interpolation values, so the test sees what is looked up.
const t = ((key: string, opts?: Record<string, unknown>) => {
  const { defaultValue, ...params } = opts ?? {};
  return `${key}|${JSON.stringify(params)}|${defaultValue ?? ''}`;
}) as unknown as TFunction;

describe('complianceActionOutcomes', () => {
  it('reads the actions of a result', () => {
    const json = JSON.stringify({ actions: [{ type: 'NOTIFY', success: true, target: 'a@example.com' }] });
    expect(complianceActionOutcomes(json)).toEqual([{ type: 'NOTIFY', success: true, target: 'a@example.com' }]);
  });

  it.each([undefined, null, '', 'not json', '{"actions": "x"}', '{"other": 1}'])('is empty for %s', (value) => {
    expect(complianceActionOutcomes(value as string | null | undefined)).toEqual([]);
  });
});

describe('labels and errors', () => {
  it('names the action with its target', () => {
    expect(complianceActionLabel(t, { type: 'ASSIGN_TAG', success: true, target: 'gov/class' })).toBe(
      'compliance:actionOutcomes.types.ASSIGN_TAG|{"target":"gov/class"}|ASSIGN_TAG gov/class',
    );
  });

  it('translates a failure code with its params', () => {
    const outcome = { type: 'ASSIGN_TAG', success: false, code: 'tag_not_found', params: { tag: 'gov/x' } };
    expect(complianceActionError(t, outcome)).toBe('compliance:actionOutcomes.errors.tag_not_found|{"tag":"gov/x"}|tag_not_found');
  });

  it('has no error text for a success, and a generic one without a code', () => {
    expect(complianceActionError(t, { type: 'NOTIFY', success: true })).toBe('');
    expect(complianceActionError(t, { type: 'NOTIFY', success: false })).toContain('errors.action_failed');
  });
});
