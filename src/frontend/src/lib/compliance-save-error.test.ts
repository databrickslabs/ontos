import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { complianceSaveErrorText } from './compliance-save-error';
import { complianceRunWarningText } from './compliance-run-warning';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

const params = { line: 2, column: 23, text: 'IS' };

describe('complianceSaveErrorText', () => {
  it('translates the trailing-input refusal with its position', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceSaveErrorText(i18n.t, {
      error: 'Rule has unparsed trailing input starting at line 2, column 23 (\'IS\')',
      errorCode: 'rule_trailing_input',
      errorParams: params,
    });

    expect(text).toContain('linha 2, coluna 23');
    expect(text).toContain("'IS'");
    expect(text).not.toContain('unparsed');
  });

  it('shows the API message for an error without a code', () => {
    expect(complianceSaveErrorText(i18n.t, { error: 'Failed to parse rule: x' }))
      .toBe('Failed to parse rule: x');
  });

  it('shows the API message for an unknown code', () => {
    expect(complianceSaveErrorText(i18n.t, { error: 'Nope', errorCode: 'unknown_code' }))
      .toBe('Nope');
  });

  it('uses the fallback when the API sent nothing', () => {
    expect(complianceSaveErrorText(i18n.t, {}, 'Save failed')).toBe('Save failed');
  });
});

describe('complianceRunWarningText', () => {
  it('translates the trailing-input warning of a run', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceRunWarningText(i18n.t, {
      warning_code: 'rule_trailing_input',
      warning_params: params,
    });

    expect(text).toContain('linha 2, coluna 23');
  });

  it('is empty for a run without a warning', () => {
    expect(complianceRunWarningText(i18n.t, { warning_code: null })).toBe('');
    expect(complianceRunWarningText(i18n.t, {})).toBe('');
  });
});
