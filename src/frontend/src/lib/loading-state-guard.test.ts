/**
 * Loading-state guardrail (#297), run in CI (ESLint has the same rules for the
 * editor, see eslint.config.js): content that loads gets a layout-matched
 * skeleton, and spinners only go through ActionSpinner.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === 'tests' ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

const files = sourceFiles(SRC).map((path) => ({
  path: relative(SRC, path),
  text: readFileSync(path, 'utf8'),
}));

describe('loading-state guardrail', () => {
  it('uses animate-spin only in ActionSpinner', () => {
    const offenders = files
      .filter((f) => f.path !== join('components', 'ui', 'action-spinner.tsx'))
      .filter((f) => /\banimate-spin\b/.test(f.text))
      .map((f) => f.path);
    expect(offenders).toEqual([]);
  });

  it('imports the Skeleton primitive only from the shared skeleton library', () => {
    const allowed = [join('components', 'common', 'list-view-skeleton.tsx'), join('components', 'ui', 'skeleton.tsx')];
    const offenders = files
      .filter((f) => !allowed.includes(f.path))
      .filter((f) => /from ['"]@\/components\/ui\/skeleton['"]/.test(f.text))
      .map((f) => f.path);
    expect(offenders).toEqual([]);
  });
});
