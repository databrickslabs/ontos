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

  it('translates a status the import mapped to draft', async () => {
    await i18n.changeLanguage('pt');

    expect(importItemLine({ index: 5, name: 'Legacy', entity_id: 'p-5', status: 'created',
      message: "'production' is not a lifecycle status, so it was imported as 'draft'.",
      code: 'imported_status_mapped', params: { status: 'production', mappedTo: 'draft' } },
    i18n.t))
      .toBe("• Legacy: 'production' não é um status do ciclo de vida, "
        + "então foi importado como 'draft'.");
  });

  it('translates older status names mapped like the database migration', async () => {
    await i18n.changeLanguage('pt');

    expect(importItemLine({ index: 7, name: 'Old', entity_id: 'p-7', status: 'created',
      message: "'archived' is an older status name, so it was imported as 'retired'.",
      code: 'imported_legacy_status', params: { status: 'archived', mappedTo: 'retired' } },
    i18n.t))
      .toBe("• Old: 'archived' é um nome de status antigo, então foi importado como 'retired'.");
    expect(importItemLine({ index: 8, name: 'Cert', entity_id: 'p-8', status: 'created',
      message: "'certified' is not a status any more, so it was imported as 'active'.",
      code: 'imported_certified_as_active', params: { status: 'certified', mappedTo: 'active' } },
    i18n.t))
      .toBe("• Cert: 'certified' não é mais um status, então foi importado como 'active'. "
        + 'A certificação não é importada: certifique a entidade no Ontos.');
  });

  it('lists every note of an item that has more than one', async () => {
    await i18n.changeLanguage('pt');

    expect(importItemLine({ index: 6, name: 'Legacy', entity_id: 'p-6', status: 'created',
      message: 'status note. replacement note.',
      code: 'imported_status_mapped', params: { status: 'production', mappedTo: 'draft' },
      notes: [{ code: 'imported_replacement_dropped', params: { replacementId: '1111' },
        message: 'replacement note.' }] }, i18n.t))
      .toBe("• Legacy: 'production' não é um status do ciclo de vida, "
        + "então foi importado como 'draft'. "
        + 'O substituto 1111 não existe aqui, então não foi vinculado.');
  });

  it('keeps the message of an unknown code or an uncoded item', () => {
    expect(importItemLine({ index: 3, name: 'X', status: 'failed', message: 'Could not import',
      code: 'something_else' }, i18n.t)).toBe('• X: Could not import');
    expect(importItemLine({ index: 4, status: 'skipped', source_id: 's-4' }, i18n.t))
      .toBe('• s-4: skipped');
  });

  it('translates a refused `certified` status', async () => {
    await i18n.changeLanguage('pt');
    const line = importItemLine(
      {
        index: 0,
        name: 'Cert Product',
        status: 'failed',
        message: "'certified' is not a status: certification is set with the certify action, "
          + 'on an active entity.',
        code: 'certified_is_not_a_status',
        params: null,
      },
      i18n.t,
    );
    expect(line).toContain('Cert Product');
    expect(line).not.toContain("'certified' is not a status");
    expect(line).toBe(`• Cert Product: ${i18n.t('workflow-gates:certifiedIsNotAStatus')}`);
  });
});
