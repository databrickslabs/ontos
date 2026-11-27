/**
 * The import summary is one translated sentence for each combination of
 * counts; it was "1 created, 1 failed" in English in every language.
 */
import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { summarizeDelivery, summarizeImport, type BatchImportResult } from './import-results';

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

describe('summarizeDelivery', () => {
  const delivered = (status: 'delivered' | 'failed' | 'skipped', index: number) => ({
    index, entity_id: `p-${index}`, status: 'created' as const, delivery: { status },
  });

  it('counts the delivered and the not delivered products', async () => {
    await i18n.changeLanguage('pt');
    const withFailure: BatchImportResult = {
      ...result(3, 0, 0), delivery_failed: 1,
      items: [delivered('delivered', 0), delivered('delivered', 1), delivered('failed', 2)],
    };
    expect(summarizeDelivery(withFailure, i18n.t)).toBe('Entregues: 2, não entregues: 1.');
  });

  it('says nothing when every delivery succeeded or no delivery mode is active', () => {
    const allDelivered: BatchImportResult = {
      ...result(2, 0, 0), delivery_failed: 0,
      items: [delivered('delivered', 0), delivered('skipped', 1)],
    };
    expect(summarizeDelivery(allDelivered, i18n.t)).toBe('');
    expect(summarizeDelivery({ ...result(2, 0, 0), items: [] }, i18n.t)).toBe('');
  });
});
