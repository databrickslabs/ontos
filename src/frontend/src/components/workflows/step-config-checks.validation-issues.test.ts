/** The errors of a refused workflow save, in the user's language. */
import { afterEach, describe, expect, it } from 'vitest';
import i18n from '@/i18n/config';
import { workflowValidationIssueText } from './step-config-checks';

describe('workflowValidationIssueText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('translates a step pointing at a step that is not in the workflow', async () => {
    const issue = {
      code: 'step_unknown_reference',
      message: "Step 'prepare' references unknown step 'old-check' in on_fail",
      params: { step: 'prepare', target: 'old-check', field: 'on_fail' },
    };
    expect(workflowValidationIssueText(issue, i18n.t)).toBe(
      'Step "prepare" points its fail branch at "old-check", which is not in the workflow.',
    );
    await i18n.changeLanguage('pt');
    expect(workflowValidationIssueText(issue, i18n.t)).toBe(
      'A etapa "prepare" aponta o ramo de falha para "old-check", que não está no workflow.',
    );
  });

  it('translates missing settings and a Conditional step issue', async () => {
    await i18n.changeLanguage('pt');
    expect(workflowValidationIssueText(
      { code: 'step_config_missing', message: 'x', params: { step: 'notify', fields: ['recipients'] } },
      i18n.t,
    )).toBe('Faltam configurações obrigatórias na etapa "notify": recipients.');
    expect(workflowValidationIssueText(
      { code: 'condition_required', message: "Step 'check': Enter a condition.", params: { step: 'check' } },
      i18n.t,
    )).toBe('Etapa "check": Informe uma condição.');
  });

  it('shows the English text of an error it has no text for', () => {
    const message = "disabled_for: unknown domain 'nope'";
    expect(workflowValidationIssueText(
      { code: 'workflow_validation_error', message, params: {} },
      i18n.t,
    )).toBe(message);
  });
});
