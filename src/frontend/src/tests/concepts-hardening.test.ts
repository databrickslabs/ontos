import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const sourceRoot = resolve(__dirname, '..');
const locales = ['de', 'es', 'fr', 'it', 'ja', 'nl', 'pt'] as const;
const namespaces = ['concepts', 'semantic-models'] as const;

function scalarPaths(value: unknown, prefix = ''): string[] {
  if (value === null || typeof value !== 'object') return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    scalarPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe('Concept UI hardening', () => {
  it('keeps Concept translation keys aligned across every supported locale', () => {
    for (const namespace of namespaces) {
      const english = JSON.parse(
        readFileSync(resolve(sourceRoot, `i18n/locales/en/${namespace}.json`), 'utf8'),
      );
      const expected = scalarPaths(english).sort();

      for (const locale of locales) {
        const translated = JSON.parse(
          readFileSync(resolve(sourceRoot, `i18n/locales/${locale}/${namespace}.json`), 'utf8'),
        );
        expect(scalarPaths(translated).sort(), `${locale}/${namespace}`).toEqual(expected);
      }
    }
  });

  it('uses Skeleton placeholders for initial Concept content loads', () => {
    const files = [
      'views/define.tsx',
      'components/concepts/guided-generate-dialog.tsx',
      'components/enrich/review-suggestions-dialog.tsx',
      'components/semantic/version-history-panel.tsx',
      'components/semantic/concept-neighborhood-graph.tsx',
      'components/semantic/linked-objects-panel.tsx',
      'components/semantic/concept-relations-panel.tsx',
      'components/semantic/turtle-serialization-panel.tsx',
    ];

    for (const file of files) {
      const source = readFileSync(resolve(sourceRoot, file), 'utf8');
      expect(source, file).toContain("@/components/ui/skeleton");
      expect(source, file).toContain('<Skeleton');
    }
  });
});
