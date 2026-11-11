/**
 * The approval dialog's request details: known payload fields, the entity
 * type and status values in the user's language; other fields as their key.
 */
import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { approvalEntityTypeLabel, approvalFieldLabel, approvalFieldValue } from './approval-payload-labels';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('approval payload labels', () => {
  it('translates the known fields and humanises the others', async () => {
    await i18n.changeLanguage('de');
    expect(approvalFieldLabel('replacement_id', i18n.t)).toBe('Ersatz-ID');
    expect(approvalFieldLabel('sunset_date', i18n.t)).toBe('Auslaufdatum');
    expect(approvalFieldLabel('unknown_field', i18n.t)).toBe('Unknown Field');
  });

  it('translates the entity type, with a humanised fallback', async () => {
    await i18n.changeLanguage('ja');
    expect(approvalEntityTypeLabel('data_contract', i18n.t)).toBe('データ契約');
    expect(approvalEntityTypeLabel('glossary_term', i18n.t)).toBe('Glossary Term');
    expect(approvalEntityTypeLabel(undefined, i18n.t)).toBe('エンティティ');
  });

  it('shows status values through the entity type\'s status labels', async () => {
    await i18n.changeLanguage('pt');
    expect(approvalFieldValue('target_status', 'under_review', 'data_contract', i18n.t)).toBe('Em Revisão');
    expect(approvalFieldValue('from_status', 'retired', 'data_product', i18n.t)).toBe('Aposentado');
    expect(approvalFieldValue('to_status', 'not_a_status', 'data_product', i18n.t)).toBe('not_a_status');
    // Other values as sent
    expect(approvalFieldValue('justification', 'active', 'data_product', i18n.t)).toBe('active');
    expect(approvalFieldValue('asset_fqns', ['a.b.c', 'a.b.d'], 'data_product', i18n.t)).toBe('a.b.c, a.b.d');
  });

  it('shows structured and non-string status values as sent', () => {
    expect(approvalFieldValue('metadata', { a: 1 }, 'data_product', i18n.t)).toBe('{"a":1}');
    // A status field only goes through the status labels when it is a string
    expect(approvalFieldValue('status', 3, 'data_product', i18n.t)).toBe('3');
    expect(approvalFieldValue('status', { code: 'x' }, 'data_product', i18n.t)).toBe('{"code":"x"}');
  });
});
