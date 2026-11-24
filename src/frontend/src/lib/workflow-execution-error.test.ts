/**
 * The executions list shows an execution's error in the user's language when
 * the backend sent the failed step's code (a rejection without a reason is
 * stored as the English "Request denied").
 */
import { describe, it, expect } from 'vitest';

import i18n from '@/i18n/config';
import { stepErrorKeys, workflowExecutionErrorText } from './workflow-execution-error';

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

  it('translates a step refused in a stored before_update gate', async () => {
    await i18n.changeLanguage('pt');
    try {
      expect(workflowExecutionErrorText(i18n.t, {
        error_message: "A delivery step can't run in a before_update gate",
        error_code: 'update_gate_step_not_allowed',
        error_params: { stepType: 'delivery' },
      }, asStored)).toBe(
        // The step type under the designer's label, not its raw value
        'Uma etapa Entrega não pode rodar em um gate before update: o que ela faz continuaria '
        + 'feito quando a atualização fosse recusada. '
        + 'Remova a etapa ou mova-a para um fluxo on update.',
      );
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('translates a WHERE clause that could not be evaluated', async () => {
    await i18n.changeLanguage('pt');
    try {
      expect(workflowExecutionErrorText(i18n.t, {
        error_message:
          "The WHERE clause of policy 'Purpose' could not be evaluated on data_contract c-1",
        error_code: 'rule_where_evaluation_failed',
        error_params: { policyName: 'Purpose', entityType: 'data_contract', entityId: 'c-1' },
      }, asStored)).toBe(
        "Não foi possível avaliar a cláusula WHERE da política 'Purpose' em data_contract c-1",
      );
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

describe('stepErrorKeys', () => {
  it('looks in the step errors, then in the script step errors', () => {
    expect(stepErrorKeys('script_python_disabled')).toEqual([
      'workflows:execution.stepErrors.script_python_disabled',
      'workflows:designer.scriptStepSafety.errors.script_python_disabled',
    ]);
  });
});

describe('workflowExecutionErrorText for a script step', () => {
  it('translates a placeholder error with its parameter', async () => {
    const execution = {
      error_message:
        "Placeholder ${entity_name} is inside quotes or backticks, where its value can't be bound.",
      error_code: 'script_sql_placeholder_in_quotes',
      error_params: { placeholder: '${entity_name}' },
    };
    expect(workflowExecutionErrorText(i18n.t, execution, asStored)).toContain(
      'The placeholder ${entity_name} is inside quotes or backticks',
    );
    await i18n.changeLanguage('pt');
    try {
      expect(workflowExecutionErrorText(i18n.t, execution, asStored)).toContain(
        'O marcador ${entity_name} está entre aspas ou crases',
      );
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('still prefers a step error text of the same code', () => {
    expect(workflowExecutionErrorText(i18n.t, {
      error_message: 'Request denied', error_code: 'approval_rejected', error_params: {},
    }, asStored)).toBe('Request denied');
  });
});
