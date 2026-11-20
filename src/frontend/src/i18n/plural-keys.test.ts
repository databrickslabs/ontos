/**
 * i18next 26 reads plural forms as `<key>_one` / `<key>_other` (JSON v4).
 * Legacy `<key>_plural` keys are never looked up, so a count above 1 would
 * render the singular base key ("5 day").
 */
import { createInstance } from 'i18next';
import { describe, expect, it } from 'vitest';

type Messages = Record<string, unknown>;

const FILES = import.meta.glob('./locales/*/*.json', { eager: true }) as Record<
  string,
  { default: Messages }
>;

function legacyPluralKeys(messages: Messages, prefix = ''): string[] {
  return Object.entries(messages).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object') return legacyPluralKeys(value as Messages, path);
    return key.endsWith('_plural') ? [path] : [];
  });
}

describe('plural keys', () => {
  it('no locale file uses the legacy _plural suffix', () => {
    const found = Object.entries(FILES).flatMap(([file, module]) =>
      legacyPluralKeys(module.default).map((key) => `${file}: ${key}`),
    );
    expect(found).toEqual([]);
  });

  it('renders the plural form for a count above 1', async () => {
    const i18n = createInstance();
    const en = FILES['./locales/en/access-grants.json'].default;
    const search = FILES['./locales/en/search.json'].default;
    await i18n.init({
      lng: 'en',
      resources: { en: { 'access-grants': en, search } },
      interpolation: { escapeValue: false },
    });
    expect(i18n.t('request.duration.days', { ns: 'access-grants', count: 5 })).toBe('5 days');
    expect(i18n.t('results', { ns: 'search', count: 5 })).toBe('5 results found');
  });
});
