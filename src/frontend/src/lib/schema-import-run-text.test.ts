/**
 * The progress of a background schema import is one sentence in the user's
 * language, with the error count only when there were errors.
 */
import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { asyncRunProgressText, asyncRunStatusLabel } from './schema-import-run-text';

const run = {
  processed_items: 3, total_items: 10, created_count: 2, skipped_count: 1, error_count: 0,
};

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('asyncRunProgressText', () => {
  it('counts the run in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    expect(asyncRunProgressText(run, i18n.t)).toBe('3 de 10 processados (criados: 2, ignorados: 1)');
    expect(asyncRunProgressText({ ...run, error_count: 4 }, i18n.t)).toBe(
      '3 de 10 processados (criados: 2, ignorados: 1, erros: 4)',
    );
  });

  it('keeps the English sentence in English', () => {
    expect(asyncRunProgressText(run, i18n.t)).toBe('3 of 10 processed (created: 2, skipped: 1)');
  });
});

describe('asyncRunStatusLabel', () => {
  it('names the status in the user language, and an unknown one as sent', async () => {
    await i18n.changeLanguage('pt');
    expect(asyncRunStatusLabel('running', i18n.t)).toBe('Em execução');
    expect(asyncRunStatusLabel('paused', i18n.t)).toBe('paused');
  });
});
