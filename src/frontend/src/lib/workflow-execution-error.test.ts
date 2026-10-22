/**
 * The executions list shows an execution's error in the user's language when
 * the backend sent the failed step's code (a rejection without a reason is
 * stored as the English "Request denied").
 */
import { describe, it, expect } from 'vitest';

import i18n from '@/i18n/config';
import { workflowExecutionErrorText } from './workflow-execution-error';

const asStored = (text: string | undefined | null) => text ?? undefined;

describe('workflowExecutionErrorText', () => {
  it('translates a rejection without a reason', async () => {
    await i18n.changeLanguage('pt');
    try {
      expect(workflowExecutionErrorText(i18n.t, {
        error_message: 'Request denied', error_code: 'approval_rejected', error_params: {},
      }, asStored)).toBe('Solicitação negada');
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('translates a coded step error with its parameters', async () => {
    await i18n.changeLanguage('pt');
    try {
      expect(workflowExecutionErrorText(i18n.t, {
        error_message: "data_product p-1 was not found, so the rule can't be evaluated",
        error_code: 'rule_entity_not_found',
        error_params: { entityType: 'data_product', entityId: 'p-1' },
      }, asStored)).toBe('data_product p-1 não foi encontrado, então a regra não pode ser avaliada');
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('passes an error without a code to the default texts', () => {
    expect(workflowExecutionErrorText(i18n.t, { error_message: 'Not ready' }, asStored))
      .toBe('Not ready');
    expect(workflowExecutionErrorText(i18n.t, { error_message: 'x' }, () => 'shipped'))
      .toBe('shipped');
  });

  it('falls back to the stored text for an unknown code', () => {
    expect(workflowExecutionErrorText(i18n.t, {
      error_message: 'Something else', error_code: 'not_a_known_code',
    }, asStored)).toBe('Something else');
  });

  it('shows nothing without an error', () => {
    expect(workflowExecutionErrorText(i18n.t, {}, asStored)).toBeUndefined();
  });
});
