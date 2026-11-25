import { describe, it, expect, afterEach } from 'vitest';

import i18n from '@/i18n/config';
import { llmCheckErrorText, llmCheckText, parseLlmChecks } from './compliance-llm-checks';
import { complianceRunWarningText } from './compliance-run-warning';

describe('compliance LLM checks', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('reads the checks of a result', () => {
    const details = JSON.stringify({
      llm_checks: [
        { criterion: 'states the grain', passed: false, reason: 'no grain', code: null },
      ],
    });

    expect(parseLlmChecks(details)).toEqual([
      { criterion: 'states the grain', passed: false, reason: 'no grain', code: null },
    ]);
  });

  it('reads nothing from results without checks', () => {
    expect(parseLlmChecks(null)).toEqual([]);
    expect(parseLlmChecks('not json')).toEqual([]);
    expect(parseLlmChecks('{"other": 1}')).toEqual([]);
  });

  it("shows the model's reason as it is and translates a code", async () => {
    await i18n.changeLanguage('de');
    const t = i18n.t.bind(i18n);

    expect(llmCheckText(t, { criterion: 'c', passed: false, reason: 'no grain' })).toBe('no grain');
    expect(llmCheckText(t, { criterion: 'c', passed: false, code: 'llm_check_budget_exceeded' }))
      .toBe('Nicht geprüft: Der Lauf hat sein Budget an Modellaufrufen erreicht.');
    expect(llmCheckText(t, { criterion: 'c', passed: false, code: 'llm_check_new' }))
      .toBe('llm_check_new');
  });

  it('translates a coded refusal and falls back to the message', async () => {
    await i18n.changeLanguage('pt');
    const t = i18n.t.bind(i18n);

    expect(llmCheckErrorText(t, {
      error: 'english',
      errorCode: 'llm_check_entity_read_required',
      errorParams: { entityType: 'data_product' },
    })).toBe(
      'Esta regra usa LLM_CHECK em entidades data_product. '
      + 'Executá-la ou testá-la exige acesso de leitura a elas.',
    );
    expect(llmCheckErrorText(t, { error: 'english', errorCode: 'unknown_code' })).toBe('english');
    expect(llmCheckErrorText(t, { error: null }, 'fallback')).toBe('fallback');
  });

  it('explains the daily quota, as a refusal and as a run warning', () => {
    const t = i18n.t.bind(i18n);

    expect(llmCheckErrorText(t, {
      error: 'english',
      errorCode: 'llm_check_daily_quota_exceeded',
      errorParams: { limit: 400, retryAfter: 120 },
    })).toBe(
      'You used your 400 LLM_CHECK model calls for today. Try again in 120 seconds '
      + '(the count starts over at midnight UTC).',
    );
    expect(complianceRunWarningText(t, {
      warning_code: 'llm_check_daily_quota_exceeded',
      warning_params: { count: 3, limit: 400 },
    })).toMatch(/^3 LLM checks were not run because you used your 400 model calls for today/);
  });
});
