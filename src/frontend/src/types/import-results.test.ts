/**
 * The import summary is one translated sentence for each combination of
 * counts; it was "1 created, 1 failed" in English in every language.
 */
import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { summarizeImport, type BatchImportResult } from './import-results';

const result = (created: number, skipped: number, failed: number): BatchImportResult => ({
  created, skipped, failed, total: created + skipped + failed, items: [], created_ids: [],
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('summarizeImport', () => {
  it('summarises in Portuguese, leaving out the zero counts', async () => {
    await i18n.changeLanguage('pt');
    expect(summarizeImport(result(1, 0, 1), i18n.t)).toBe('Criados: 1, com falha: 1.');
    expect(summarizeImport(result(2, 1, 0), i18n.t)).toBe('Criados: 2, ignorados: 1.');
    expect(summarizeImport(result(0, 1, 3), i18n.t)).toBe('Criados: 0, ignorados: 1, com falha: 3.');
    expect(summarizeImport(result(4, 0, 0), i18n.t)).toBe('Criados: 4.');
  });

  it('summarises in English and Japanese', async () => {
    expect(summarizeImport(result(1, 0, 1), i18n.t)).toBe('Created: 1, failed: 1.');
    await i18n.changeLanguage('ja');
    expect(summarizeImport(result(3, 1, 2), i18n.t)).toBe('作成: 3 件、スキップ: 1 件、失敗: 2 件。');
  });
});
