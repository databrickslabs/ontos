/**
 * The upload success toast is one translated sentence per case, with the
 * product count in the language's plural form.
 */
import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { productUploadSuccessText } from './upload-text';

const file = (name: string) => ({ name });

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('productUploadSuccessText', () => {
  it('counts several files in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    expect(productUploadSuccessText([file('a.yaml'), file('b.yaml'), file('c.yaml')], 5, i18n.t))
      .toBe('3 arquivos processados com sucesso. 5 produtos processados.');
  });

  it('names a single file, with the singular for one product', async () => {
    await i18n.changeLanguage('pt');
    expect(productUploadSuccessText([file('sales.yaml')], 1, i18n.t))
      .toBe('sales.yaml processado com sucesso. 1 produto processado.');
  });

  it('uses the plural forms in English and German', async () => {
    expect(productUploadSuccessText([file('a.yaml'), file('b.yaml')], 1, i18n.t))
      .toBe('Successfully processed 2 files. 1 product processed.');
    await i18n.changeLanguage('de');
    expect(productUploadSuccessText([file('a.yaml')], 4, i18n.t))
      .toBe('a.yaml erfolgreich verarbeitet. 4 Produkte verarbeitet.');
  });

  it('counts the imported contracts in the plural form', async () => {
    await i18n.changeLanguage('fr');
    expect(i18n.t('data-contracts:messages.uploadSuccessCount', { count: 1 })).toBe('1 contrat importé avec succès');
    expect(i18n.t('data-contracts:messages.uploadSuccessCount', { count: 2 })).toBe('2 contrats importés avec succès');
  });
});
