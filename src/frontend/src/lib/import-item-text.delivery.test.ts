/**
 * Import report lines for a created product that wasn't delivered (Git, Unity
 * Catalog) after its import committed it (#1385 review).
 */
import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import type { BatchImportResult } from '@/types/import-results';
import { importItemLine, reportedImportItems } from './import-item-text';

describe('import report lines of an undelivered product', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('lists a created item that was not delivered, with the reason translated', async () => {
    await i18n.changeLanguage('pt');
    const result: BatchImportResult = {
      created: 2, skipped: 0, failed: 0, total: 2, created_ids: ['p-1', 'p-2'],
      delivery_failed: 1,
      items: [
        { index: 0, name: 'Delivered', entity_id: 'p-1', status: 'created',
          delivery: { status: 'delivered', params: { modes: ['indirect'] } } },
        { index: 1, name: 'Orders', entity_id: 'p-2', status: 'created',
          delivery: { status: 'failed', code: 'delivery_git_unavailable',
            params: { mode: 'indirect' } } },
      ],
    };

    expect(reportedImportItems(result).map((i) => i.name)).toEqual(['Orders']);
    expect(importItemLine(result.items[1], i18n.t)).toBe(
      '• Orders: Importado, mas não entregue: o repositório Git não está disponível. '
        + 'Verifique Configurações > Git.');
  });

  it('adds the delivery reason after a note, and reads an unknown code as a failure', () => {
    expect(importItemLine({ index: 2, name: 'Legacy', entity_id: 'p-3', status: 'created',
      message: 'A note', delivery: { status: 'failed', code: 'something_new' } }, i18n.t))
      .toBe('• Legacy: A note Imported, but not delivered. The server logs have the details.');
  });
});
