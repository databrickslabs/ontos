/**
 * Tests for the DomainMultiSelector selection logic (#520 multi-domain).
 *
 * We test the exported pure helpers rather than rendering the component, because
 * the underlying Radix <Popover>/<Command> hangs in jsdom (see trigger-picker /
 * role-form-dialog tests for the same convention).
 */
import { describe, it, expect } from 'vitest';

import {
  addDomainToSelection,
  removeDomainFromSelection,
  resolveEffectivePrimary,
} from './domain-multi-selector';

describe('resolveEffectivePrimary', () => {
  it('returns null for an empty selection', () => {
    expect(resolveEffectivePrimary([], null)).toBeNull();
  });

  it('falls back to the first selected domain when no primary is set', () => {
    expect(resolveEffectivePrimary(['a', 'b'], null)).toBe('a');
  });

  it('keeps the explicit primary when it is still selected', () => {
    expect(resolveEffectivePrimary(['a', 'b'], 'b')).toBe('b');
  });

  it('falls back to the first when the explicit primary is no longer selected', () => {
    expect(resolveEffectivePrimary(['a', 'b'], 'z')).toBe('a');
  });
});

describe('addDomainToSelection', () => {
  it('makes the first added domain the primary', () => {
    expect(addDomainToSelection([], null, 'a')).toEqual({ domainIds: ['a'], primaryDomainId: 'a' });
  });

  it('appends without changing the existing primary', () => {
    expect(addDomainToSelection(['a'], 'a', 'b')).toEqual({ domainIds: ['a', 'b'], primaryDomainId: 'a' });
  });

  it('is a no-op when the domain is already selected', () => {
    expect(addDomainToSelection(['a', 'b'], 'a', 'b')).toEqual({ domainIds: ['a', 'b'], primaryDomainId: 'a' });
  });

  it('respects maxDomains', () => {
    expect(addDomainToSelection(['a'], 'a', 'b', 1)).toEqual({ domainIds: ['a'], primaryDomainId: 'a' });
  });
});

describe('removeDomainFromSelection', () => {
  it('removes a non-primary domain and keeps the primary', () => {
    expect(removeDomainFromSelection(['a', 'b'], 'a', 'b')).toEqual({ domainIds: ['a'], primaryDomainId: 'a' });
  });

  it('promotes the first remaining domain when the primary is removed', () => {
    expect(removeDomainFromSelection(['a', 'b'], 'a', 'a')).toEqual({ domainIds: ['b'], primaryDomainId: 'b' });
  });

  it('leaves no primary when the last domain is removed', () => {
    expect(removeDomainFromSelection(['a'], 'a', 'a')).toEqual({ domainIds: [], primaryDomainId: null });
  });
});
