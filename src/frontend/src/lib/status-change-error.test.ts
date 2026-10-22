/**
 * A blocked status change's error in the user's language (#1078).
 */
import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { apiErrorOf, statusChangeErrorText } from './status-change-error';

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

  it('translates the deprecation checks with their parameters', async () => {
    await i18n.changeLanguage('pt');

    expect(statusChangeErrorText({
      error: 'Replacement p-2 is deprecated; it is replaced by p-3',
      errorCode: 'replacement_deprecated_replaced',
      errorParams: { replacementId: 'p-2', replacedBy: 'p-3' },
    }, i18n.t, 'data-products')).toBe('O substituto p-2 está obsoleto; ele é substituído por p-3.');
    expect(statusChangeErrorText({
      error: 'The sunset date 2026-10-18 is in the past',
      errorCode: 'sunset_date_in_past',
      errorParams: { sunsetDate: '2026-10-18' },
    }, i18n.t, 'data-contracts')).toBe('A data de desativação 2026-10-18 está no passado.');
  });

  it('keeps the English text for a deprecation code without a translation', async () => {
    await i18n.changeLanguage('pt');

    expect(statusChangeErrorText(
      { error: 'Something new', errorCode: 'not_a_deprecation_code' }, i18n.t, 'data-products',
    )).toBe('Something new');
  });

  it('translates an edit that tries to change the status', async () => {
    await i18n.changeLanguage('pt');

    expect(statusChangeErrorText({
      error: "An update can't change the status from 'active' to 'deprecated'. ...",
      errorCode: 'status_change_requires_transition',
      errorParams: { fromStatus: 'active', toStatus: 'deprecated' },
    }, i18n.t, 'data-products')).toBe(
      'Uma edição não pode mudar o status de Ativo para Obsoleto. Use Alterar status, '
      + 'que verifica a transição e executa os workflows de mudança de status.',
    );
  });

  it('translates a status that is not a lifecycle one', async () => {
    await i18n.changeLanguage('pt');

    expect(statusChangeErrorText(
      { error: "'certified' is not a status", errorCode: 'certified_is_not_a_status' },
      i18n.t, 'data-contracts',
    )).toBe('Certificado não é um status: a certificação é definida com Certificar, numa entidade ativa.');
    expect(statusChangeErrorText({
      error: "'archived' is not a lifecycle status.",
      errorCode: 'invalid_status',
      errorParams: { status: 'archived', allowed: ['draft', 'active'] },
    }, i18n.t, 'data-contracts')).toBe('archived não é um status do ciclo de vida. Use um destes: Rascunho, Ativo.');
  });

  it('translates a fail_closed gate that could not be evaluated (#1103)', async () => {
    const gateError = {
      error: "Status transition from 'draft' to 'proposed' refused: a workflow gate "
        + '(Enforcement Gate) could not be evaluated. Ask an administrator to check the workflow.',
      errorCode: 'status_change_gate_error',
      errorParams: { fromStatus: 'draft', toStatus: 'proposed', workflows: ['Enforcement Gate'] },
    };
    expect(statusChangeErrorText(gateError, i18n.t, 'data-products')).toBe(
      'The status change from Draft to Proposed was refused: the workflow gate Enforcement Gate '
      + 'could not be evaluated. Ask an administrator to check the workflow.',
    );

    await i18n.changeLanguage('pt');
    expect(statusChangeErrorText(gateError, i18n.t, 'data-products')).toBe(
      'A mudança de status de Rascunho para Proposto foi recusada: não foi possível avaliar o gate '
      + 'de workflow Enforcement Gate. Peça a um administrador para verificar o workflow.',
    );
    // The gates couldn't be listed: no names
    expect(statusChangeErrorText(
      { ...gateError, errorParams: { fromStatus: 'draft', toStatus: 'proposed', workflows: [] } },
      i18n.t, 'data-contracts',
    )).toBe(
      'A mudança de status de Rascunho para Proposto foi recusada: não foi possível avaliar um gate '
      + 'de workflow. Peça a um administrador para verificar o workflow.',
    );
  });
});

describe('apiErrorOf', () => {
  it('reads a coded detail, a text detail and anything else', () => {
    expect(apiErrorOf({ detail: { code: 'invalid_status', message: 'Bad', params: { status: 'x' } } }, 'F'))
      .toEqual({ error: 'Bad', errorCode: 'invalid_status', errorParams: { status: 'x' } });
    expect(apiErrorOf({ detail: 'Not found' }, 'F')).toEqual({ error: 'Not found', errorCode: null, errorParams: null });
    expect(apiErrorOf({ detail: [{ msg: 'field required' }] }, 'F')).toEqual({ error: 'F', errorCode: null, errorParams: null });
    expect(apiErrorOf(null, 'F')).toEqual({ error: 'F', errorCode: null, errorParams: null });
  });
});
