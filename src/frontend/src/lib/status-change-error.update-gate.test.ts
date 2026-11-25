/**
 * A contract update refused by its before_update gates is shown in the user's
 * language from the code the API sends (#1403 review): a fail_closed gate that
 * couldn't be evaluated, and a gate's or the update's own tags not written.
 */
import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { apiErrorOf, statusChangeErrorText } from './status-change-error';

const refused = (code: string, params: Record<string, unknown>, message = 'Update refused') =>
  apiErrorOf({ detail: { code, message, params } }, 'Update failed');

describe('statusChangeErrorText for update gates', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('names the fail_closed gates that could not be evaluated', async () => {
    await i18n.changeLanguage('pt');
    expect(statusChangeErrorText(
      refused('update_gate_error', { workflows: ['PII gate', 'Owner gate'] }), i18n.t,
      'data-contracts',
    )).toBe(
      'A atualização foi recusada: o gate de workflow PII gate, Owner gate não pôde ser '
      + 'avaliado. Peça a um administrador que verifique o workflow.',
    );
  });

  it('has a message for gates that could not even be listed', () => {
    expect(statusChangeErrorText(
      refused('update_gate_error', { workflows: [] }), i18n.t, 'data-contracts',
    )).toBe(
      'The update was refused: a workflow gate could not be evaluated. '
      + 'Ask an administrator to check the workflow.',
    );
  });

  it('translates the tag writes that refuse the update', async () => {
    await i18n.changeLanguage('de');
    expect(statusChangeErrorText(
      refused('update_gate_tag_write_failed', { entityId: 'c-1' }), i18n.t, 'data-contracts',
    )).toContain('Eine Tag-Änderung ihrer Workflow-Gates');
    expect(statusChangeErrorText(
      refused('update_gate_tag_list_write_failed', { entityId: 'c-1' }), i18n.t,
      'data-contracts',
    )).toContain('Ihre Tags, die ihre Workflow-Gates geprüft haben');
  });

  it('keeps the API message for an uncoded refusal', () => {
    expect(statusChangeErrorText(
      apiErrorOf({ detail: { message: 'Pre-update validation failed' } }, 'Update failed'),
      i18n.t, 'data-contracts',
    )).toBe('Pre-update validation failed');
  });
});
