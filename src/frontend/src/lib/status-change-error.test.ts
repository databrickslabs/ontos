/**
 * A blocked status change's error in the user's language (#1078).
 */
import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { statusChangeErrorText } from './status-change-error';

const MESSAGE = "Status transition from 'deprecated' to 'active' blocked by workflow: "
  + 'Steward Gate: waiting for approval (Steward approval); Owner Gate: Add an owner before activating; '
  + 'Rule Gate: Could not load data_product p-1 to evaluate the rule; Old Gate: cancelled';

const BLOCKED = {
  error: MESSAGE,
  errorCode: 'status_change_blocked',
  errorParams: {
    fromStatus: 'deprecated',
    toStatus: 'active',
    reasons: [
      { workflow: 'Steward Gate', text: 'waiting for approval (Steward approval)',
        code: 'waiting_for_approval', params: { step: 'Steward approval' } },
      { workflow: 'Owner Gate', text: 'Add an owner before activating' },
      { workflow: 'Rule Gate', text: 'Could not load data_product p-1 to evaluate the rule',
        code: 'rule_entity_load_failed', params: { entityType: 'data_product', entityId: 'p-1' } },
      { workflow: 'Old Gate', text: 'cancelled', code: 'execution_status', params: { status: 'cancelled' } },
    ],
  },
};

describe('statusChangeErrorText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('translates the parts the app writes and keeps the admin text as written', async () => {
    await i18n.changeLanguage('pt');

    expect(statusChangeErrorText(BLOCKED, i18n.t, 'data-products')).toBe(
      'A mudança de status de Obsoleto para Ativo foi bloqueada por um workflow: '
      + 'Steward Gate: aguardando aprovação (Steward approval); '
      + 'Owner Gate: Add an owner before activating; '
      + 'Rule Gate: não foi possível carregar data_product p-1 para avaliar a regra; '
      + 'Old Gate: cancelado',
    );
  });

  it('reads the same in English', () => {
    expect(statusChangeErrorText(BLOCKED, i18n.t, 'data-contracts')).toBe(
      'The status change from Deprecated to Active was blocked by a workflow: '
      + 'Steward Gate: waiting for approval (Steward approval); '
      + 'Owner Gate: Add an owner before activating; '
      + 'Rule Gate: could not load data_product p-1 to evaluate the rule; '
      + 'Old Gate: cancelled',
    );
  });

  it('says the validation failed when there is no reason', async () => {
    await i18n.changeLanguage('pt');

    expect(statusChangeErrorText(
      { ...BLOCKED, errorParams: { fromStatus: 'draft', toStatus: 'active', reasons: [] } },
      i18n.t, 'data-products',
    )).toBe('A mudança de status de Rascunho para Ativo foi bloqueada por um workflow: a validação do workflow falhou');
  });

  it('shows any other error as the API sent it', async () => {
    await i18n.changeLanguage('pt');

    expect(statusChangeErrorText({ error: 'Product not found' }, i18n.t, 'data-products'))
      .toBe('Product not found');
    // Without the parameters (a backend that doesn't send them) the text is the API's
    expect(statusChangeErrorText({ error: MESSAGE, errorCode: 'status_change_blocked' }, i18n.t, 'data-products'))
      .toBe(MESSAGE);
  });
});
