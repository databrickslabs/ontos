import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { complianceResultMessageText, complianceRunWarningText } from './compliance-run-warning';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

const sources = 'system.access.table_lineage';

describe('complianceRunWarningText for sources that could not be read', () => {
  it('translates the warning and each reason', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceRunWarningText(i18n.t, {
      warning_code: 'rule_fields_unavailable',
      warning_params: { count: 3, sources, reasons: 'no_access, no_warehouse' },
    });

    expect(text).toContain('Objetos não avaliados: 3');
    expect(text).toContain(sources);
    expect(text).toContain('sem acesso à tabela de sistema, nenhum SQL warehouse configurado');
  });

  it('shows an unknown reason code as it is', () => {
    const text = complianceRunWarningText(i18n.t, {
      warning_code: 'rule_fields_unavailable',
      warning_params: { count: 1, sources, reasons: 'new_reason' },
    });

    expect(text).toContain('(new_reason)');
  });
});

describe('complianceResultMessageText', () => {
  const details = JSON.stringify({
    code: 'rule_field_unavailable',
    params: { fields: 'upstream_count', sources, reason: 'no_warehouse' },
  });

  it('translates a result that was not evaluated', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceResultMessageText(i18n.t, {
      message: 'Not evaluated: upstream_count could not be read',
      details_json: details,
    });

    expect(text).toBe(
      `Não avaliado: não foi possível ler upstream_count de ${sources} ` +
        '(nenhum SQL warehouse configurado).',
    );
  });

  it('keeps the stored message without a known code', () => {
    expect(complianceResultMessageText(i18n.t, { message: 'Assertion failed' }))
      .toBe('Assertion failed');
    expect(complianceResultMessageText(i18n.t, { message: 'x', details_json: '{"code":"y"}' }))
      .toBe('x');
    expect(complianceResultMessageText(i18n.t, { message: 'x', details_json: 'not json' }))
      .toBe('x');
    expect(complianceResultMessageText(i18n.t, {})).toBe('');
  });
});
