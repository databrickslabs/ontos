import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { complianceRunWarningText } from './compliance-run-warning';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('complianceRunWarningText: a run that matched no entities', () => {
  const run = { warning_code: 'no_entities_matched', warning_params: null };

  it('says so in English', () => {
    expect(complianceRunWarningText(i18n.t, run))
      .toBe(
        'No entities matched this rule, so nothing was checked. '
        + 'Check its MATCH type and WHERE condition.',
      );
  });

  it('says so in Portuguese', async () => {
    await i18n.changeLanguage('pt');

    const text = complianceRunWarningText(i18n.t, run);

    expect(text).toContain('Nenhuma entidade corresponde a esta regra');
    expect(text).not.toBe('no_entities_matched');
  });
});
