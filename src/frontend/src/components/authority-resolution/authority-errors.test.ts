/**
 * Coded Authority Resolution errors map to translated text; unknown codes keep the server message.
 */
import { describe, it, expect } from 'vitest';
import i18n from '@/i18n/config';
import { authorityErrorMessage } from './authority-errors';

const t = (key: string, options?: any) => i18n.t(key, { ns: 'authority-resolution', ...options }) as string;

describe('authorityErrorMessage', () => {
  it('maps the 409 codes to their translated text', () => {
    expect(authorityErrorMessage(t, 'raw', 'authority_immutable')).toBe(i18n.t('authority-resolution:errors.immutable'));
    expect(authorityErrorMessage(t, 'raw', 'authority_has_history')).toBe(i18n.t('authority-resolution:errors.hasHistory'));
    expect(authorityErrorMessage(t, 'raw', 'authority_duplicate_version', { version: '2.0.0' }))
      .toContain('2.0.0');
  });

  it('maps every status conflict reason and never shows the raw text for a known reason', () => {
    for (const reason of [
      'no_enabled_checks', 'not_measured', 'dna_stale', 'ceiling_exceeded',
      'affirmations_missing', 'affirmations_stale', 'transition_not_allowed',
    ]) {
      const text = authorityErrorMessage(t, 'server text', 'authority_status_conflict', { reason });
      expect(text).toBe(i18n.t(`authority-resolution:errors.statusConflict.${reason}`));
      expect(text).not.toBe('server text');
    }
  });

  it('falls back to the server message for an unknown status reason or code', () => {
    expect(authorityErrorMessage(t, 'server text', 'authority_status_conflict', { reason: 'new_reason' })).toBe('server text');
    expect(authorityErrorMessage(t, 'server text', 'authority_invalid')).toBe('server text');
    expect(authorityErrorMessage(t, 'server text', null)).toBe('server text');
  });

  it('uses the generic text when there is neither a code nor a message', () => {
    expect(authorityErrorMessage(t, null, null)).toBe(i18n.t('authority-resolution:errors.generic'));
  });
});
