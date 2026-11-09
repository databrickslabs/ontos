import { describe, expect, it } from 'vitest';
import i18next from 'i18next';

import en from '@/i18n/locales/en/compliance.json';
import pt from '@/i18n/locales/pt/compliance.json';
import { formatRuleWarning } from './compliance-rule-warnings';

async function translator(lng: string) {
  const i18n = i18next.createInstance();
  await i18n.init({
    lng,
    resources: { en: { compliance: en }, pt: { compliance: pt } },
    interpolation: { escapeValue: false },
  });
  return i18n.t.bind(i18n);
}

const unsupported = {
  code: 'unsupported_match_type',
  params: { type: 'Dataset', supported: 'table, data_product' },
  message: "MATCH type 'Dataset' is not supported (English message from the API).",
};

describe('formatRuleWarning', () => {
  it('translates a known warning with its parameters', async () => {
    expect(formatRuleWarning(await translator('pt'), unsupported)).toBe(
      "O tipo 'Dataset' do MATCH não é suportado, então a regra não avalia nenhuma entidade. " +
        'Tipos suportados: table, data_product, ou Object para todos eles.',
    );
  });

  it('uses the English translation in English', async () => {
    const t = await translator('en');
    expect(formatRuleWarning(t, { code: 'missing_assert', params: {}, message: 'x' })).toBe(
      'The rule has no ASSERT clause, so every entity passes.',
    );
  });

  it("falls back to the API's message for an unknown code", async () => {
    const t = await translator('pt');
    expect(formatRuleWarning(t, { code: 'something_new', message: 'Plain English text.' })).toBe(
      'Plain English text.',
    );
  });
});
