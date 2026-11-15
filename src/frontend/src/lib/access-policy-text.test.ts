/**
 * Translated Access Policies text: every code the backend emits has an English string that only uses
 * the params the backend sends, and an unknown code falls back to the backend's English message.
 */
import { describe, expect, it } from 'vitest';
import i18next from 'i18next';
import codes from '@/i18n/access-policy-codes.json';
import en from '@/i18n/locales/en/access-policies.json';
import de from '@/i18n/locales/de/access-policies.json';
import { actionLabel, errorText, issueText, operandLabel, profileKey, shaclText } from './access-policy-text';

const i18n = i18next.createInstance();
await i18n.init({
  lng: 'de',
  fallbackLng: 'en',
  ns: ['access-policies'],
  resources: { en: { 'access-policies': en }, de: { 'access-policies': de } },
  interpolation: { escapeValue: false },
});
const t = i18n.t.bind(i18n);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const deText = de as any;
const issues = (en as unknown as { issues: Record<string, string> }).issues;
const placeholders = (s: string) => [...s.matchAll(/{{\s*(\w+)\s*}}/g)].map((m) => m[1]);

describe('backend codes', () => {
  const emitted = Object.entries(codes as Record<string, string[] | null>).filter(([code]) => code !== 'message');

  it.each(emitted)('%s has an English string', (code) => {
    expect(issues[code]).toBeTruthy();
  });

  it.each(emitted.filter(([, params]) => params !== null))('%s only uses params the backend sends', (code, params) => {
    for (const p of placeholders(issues[code])) expect(params).toContain(p);
  });

  it('has no English string for a code the backend no longer emits', () => {
    expect(Object.keys(issues).filter((c) => !(c in codes))).toEqual([]);
  });
});

describe('issueText', () => {
  it('translates a known code with its params', () => {
    const text = issueText(t, { code: 'unknown_action', params: { action: 'fly' }, message: "Unknown action 'fly'" });
    expect(text).toContain('fly');
    expect(text).not.toBe("Unknown action 'fly' (not in the Ontos profile)");
  });

  it('falls back to the message for an unknown code', () => {
    expect(issueText(t, { code: 'not_a_real_code', params: {}, message: 'Server said so' })).toBe('Server said so');
  });

  it('shows the message of an uncoded problem', () => {
    expect(issueText(t, { code: 'message', params: {}, message: 'Plain text' })).toBe('Plain text');
    expect(issueText(t, 'A string problem')).toBe('A string problem');
  });

  it('translates status params', () => {
    const text = issueText(t, { code: 'delete_status', params: { status: 'active' }, message: '' });
    expect(text).toContain(deText.status.active);
  });
});

describe('errorText', () => {
  it('uses the fallback without an error and the raw error without a code', () => {
    expect(errorText(t, { error: null }, 'fallback')).toBe('fallback');
    expect(errorText(t, { error: 'boom' })).toBe('boom');
  });

  it('translates a coded error', () => {
    expect(errorText(t, { error: 'Release not found', errorCode: 'release_not_found', errorParams: {} })).toBe(
      deText.issues.release_not_found,
    );
  });
});

describe('profile and SHACL labels', () => {
  it('maps prefixed keys', () => {
    expect(profileKey('ontos:browse')).toBe('ontos_browse');
  });

  it('translates actions and operands, falling back to the backend label', () => {
    expect(actionLabel(t, 'ontos:browse', 'Browse')).toBe(
      deText.profile.actions.ontos_browse.label,
    );
    expect(actionLabel(t, 'ontos:future', 'Future')).toBe('Future');
    expect(operandLabel(t, 'unknownOperand', null)).toBe('unknownOperand');
  });

  it('translates a SHACL result per constraint with the local path name', () => {
    const text = shaclText(t, {
      constraint: 'MinCountConstraintComponent',
      path: 'http://www.w3.org/ns/odrl/2/target',
      message: 'A permission names its target asset',
    });
    expect(text).toContain('target');
    expect(shaclText(t, { constraint: null, message: 'Shape says' })).toBe('Shape says');
  });
});
