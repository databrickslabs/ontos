import { describe, it, expect } from 'vitest';
import type { TFunction } from 'i18next';
import { domainParentErrorText } from './domain-parent-error';

const t = ((key: string) => `T(${key})`) as unknown as TFunction;

describe('domainParentErrorText', () => {
  it('translates a missing parent', () => {
    expect(domainParentErrorText({ error: 'x', errorCode: 'domain_parent_not_found' }, t))
      .toBe('T(data-domains:form.parentErrors.notFound)');
  });

  it('translates a parent cycle', () => {
    expect(domainParentErrorText({ error: 'x', errorCode: 'domain_parent_cycle' }, t))
      .toBe('T(data-domains:form.parentErrors.cycle)');
  });

  it('translates a loop already stored above the parent', () => {
    expect(domainParentErrorText({ error: 'x', errorCode: 'domain_hierarchy_cycle' }, t))
      .toBe('T(data-domains:form.parentErrors.existingCycle)');
  });

  it('shows any other error as the API sent it', () => {
    expect(domainParentErrorText({ error: 'boom', errorCode: 'other' }, t)).toBe('boom');
    expect(domainParentErrorText({ error: 'boom' }, t)).toBe('boom');
  });
});
