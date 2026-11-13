import { describe, it, expect } from 'vitest';

// Every locale must carry the compliance templates UI keys (no English fallback).
const compliance = import.meta.glob('./locales/*/compliance.json', {
  eager: true,
  import: 'default',
}) as Record<string, Record<string, unknown>>;
const settings = import.meta.glob('./locales/*/settings.json', {
  eager: true,
  import: 'default',
}) as Record<string, { tabs?: Record<string, string> }>;

function keyPaths(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object') return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) =>
    keyPaths(v, prefix ? `${prefix}.${k}` : k),
  );
}

const locale = (path: string) => path.split('/')[2];

describe('compliance templates locale keys', () => {
  const en = keyPaths(compliance['./locales/en/compliance.json'].complianceTemplates).sort();

  it.each(Object.keys(compliance).map(locale))('%s has every key', (code) => {
    const block = compliance[`./locales/${code}/compliance.json`].complianceTemplates;
    expect(keyPaths(block).sort()).toEqual(en);
    expect(settings[`./locales/${code}/settings.json`].tabs?.complianceTemplates).toBeTruthy();
  });

  it('covers the settings page, the editor, the modal and the value types', () => {
    for (const group of ['settings', 'dialog', 'deleteDialog', 'toast', 'valueTypes', 'modal']) {
      expect(en.some((k) => k.startsWith(`${group}.`))).toBe(true);
    }
  });
});
