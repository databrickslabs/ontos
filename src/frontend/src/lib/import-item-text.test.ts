/**
 * Import report lines: notes on created entities, translated when coded (#1042).
 */
import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import type { BatchImportResult } from '@/types/import-results';
import { importItemLine, reportedImportItems } from './import-item-text';

const RESULT: BatchImportResult = {
  created: 2, skipped: 0, failed: 1, total: 3, created_ids: ['p-1', 'p-2'],
  items: [
    { index: 0, name: 'Orders', entity_id: 'p-1', status: 'created' },
    { index: 1, name: 'Old Orders', entity_id: 'p-2', status: 'created',
      message: 'ontosReplacedBy 1111 not linked: no such entity here',
      code: 'imported_replacement_dropped', params: { replacementId: '1111' } },
    { index: 2, name: 'Broken', status: 'failed',
      message: "Invalid ontosSunsetDate 'soon': expected an ISO date",
      code: 'imported_date_invalid', params: { property: 'ontosSunsetDate', value: 'soon' } },
  ],
};

describe('import report lines', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('lists the items not created and the created ones with a note', () => {
    expect(reportedImportItems(RESULT).map((i) => i.name)).toEqual(['Old Orders', 'Broken']);
  });

  it('translates a coded note in the UI language', async () => {
    await i18n.changeLanguage('pt');

    expect(importItemLine(RESULT.items[1], i18n.t)).toBe(
      '• Old Orders: O substituto 1111 não existe aqui, então não foi vinculado.');
    expect(importItemLine(RESULT.items[2], i18n.t)).toBe(
      '• Broken: ontosSunsetDate inválido "soon": esperada uma data ISO.');
  });

  it('keeps the message of an unknown code or an uncoded item', () => {
    expect(importItemLine({ index: 3, name: 'X', status: 'failed', message: 'Could not import',
      code: 'something_else' }, i18n.t)).toBe('• X: Could not import');
    expect(importItemLine({ index: 4, status: 'skipped', source_id: 's-4' }, i18n.t))
      .toBe('• s-4: skipped');
  });
});
