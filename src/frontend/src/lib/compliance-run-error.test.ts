import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { complianceRunErrorText } from './compliance-run-error';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('complianceRunErrorText', () => {
  it('translates a run error that has a code', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceRunErrorText(i18n.t, {
      error_message: 'Failed to parse rule: Parser error at line 1',
      error_code: 'rule_parse_failed',
      error_params: { detail: 'Parser error at line 1' },
    });

    expect(text).toBe('Não foi possível interpretar a regra: Parser error at line 1');
  });

  it('translates the tag-load error with its entity type', async () => {
    await i18n.changeLanguage('pt');
    const text = complianceRunErrorText(i18n.t, {
      error_message: 'Could not load the tags of data_product entities',
      error_code: 'tags_load_failed',
      error_params: { entityType: 'data_product' },
    });

    expect(text).toBe(
      'Não foi possível carregar as tags das entidades data_product, por isso a regra não pôde ser avaliada.',
    );
  });

  it('shows the stored message when there is no code', async () => {
    await i18n.changeLanguage('pt');
    expect(complianceRunErrorText(i18n.t, { error_message: 'connection reset' })).toBe('connection reset');
  });

  it('shows the stored message for a code without a translation', async () => {
    await i18n.changeLanguage('pt');
    expect(
      complianceRunErrorText(i18n.t, { error_message: 'Something new', error_code: 'not_a_known_code' }),
    ).toBe('Something new');
  });
});
