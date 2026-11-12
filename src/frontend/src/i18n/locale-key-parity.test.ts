/**
 * Every locale has the same keys as English in the data contract, data
 * product, workflow, data domain, database schema and default workflow text
 * namespaces, so no text falls back to English.
 */
import { describe, expect, it } from 'vitest';

type Messages = Record<string, unknown>;

const FILES = import.meta.glob(
  './locales/*/{data-contracts,data-products,workflows,data-domains,database-schema,workflowDefaults}.json',
  { eager: true },
) as Record<string, { default: Messages }>;

// Plural forms that only some languages use (`_many` in Portuguese, Spanish,
// French and Italian; `_few`, `_two`, `_zero` in others): a locale may add
// them, so they aren't compared. `_one` and `_other`, which English has, are.
const LANGUAGE_PLURALS = /_(zero|two|few|many)$/;

function keys(messages: Messages, prefix = ''): string[] {
  return Object.entries(messages).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object') return keys(value as Messages, path);
    return LANGUAGE_PLURALS.test(key) ? [] : [path];
  });
}

const byNamespace: Record<string, Record<string, Messages>> = {};
for (const [path, module] of Object.entries(FILES)) {
  const [, locale, file] = /\.\/locales\/([^/]+)\/([^/]+)\.json$/.exec(path)!;
  (byNamespace[file] ??= {})[locale] = module.default;
}

describe.each(Object.keys(byNamespace))('%s', (namespace) => {
  const english = keys(byNamespace[namespace].en).sort();

  it.each(Object.keys(byNamespace[namespace]).filter((l) => l !== 'en'))(
    '%s has the same keys as English',
    (locale) => {
      expect(keys(byNamespace[namespace][locale]).sort()).toEqual(english);
    },
  );
});

describe('plural forms', () => {
  it('ignores the forms only some languages have', () => {
    expect(keys({ items_one: '1', items_many: 'n', items_other: 'n', n: { a_few: 'x' } }))
      .toEqual(['items_one', 'items_other']);
  });
});
