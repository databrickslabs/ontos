import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { internalErrorText, serverErrorText, tagValueNotAllowedText, userTokenRequiredText } from './server-error-text';

const body = {
  detail: 'An unexpected error occurred. The details are in the server log (error id 3f2a9c81d0be).',
  code: 'internal_error',
  params: { errorId: '3f2a9c81d0be' },
};

describe('internalErrorText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('gives an unexpected server error in the user language, from the parsed body or its text', async () => {
    await i18n.changeLanguage('pt');
    const portuguese = 'Ocorreu um erro inesperado. Os detalhes estão no log do servidor (id do erro 3f2a9c81d0be).';

    expect(internalErrorText(body)).toBe(portuguese);
    expect(internalErrorText(JSON.stringify(body))).toBe(portuguese);
  });

  it('gives nothing for any other error', () => {
    expect(internalErrorText({ detail: 'Failed to create contract' })).toBeNull();
    expect(internalErrorText({ detail: { code: 'status_change_blocked', message: 'x' } })).toBeNull();
    expect(internalErrorText('Internal Server Error')).toBeNull();
    expect(internalErrorText(null)).toBeNull();
  });
});

const refused = {
  detail: {
    code: 'user_token_required',
    message: "This request needs the user's Databricks token, and it has none.",
    params: {},
  },
};

describe('userTokenRequiredText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('gives a missing user token in the user language, from the body or its text', async () => {
    await i18n.changeLanguage('pt');
    const portuguese = i18n.t('errors:userTokenRequired');

    expect(portuguese).toContain('token de acesso do Databricks');
    expect(userTokenRequiredText(refused)).toBe(portuguese);
    expect(userTokenRequiredText(JSON.stringify(refused))).toBe(portuguese);
    expect(serverErrorText(refused)).toBe(portuguese);
  });

  it('gives nothing for any other error', () => {
    expect(userTokenRequiredText(body)).toBeNull();
    expect(userTokenRequiredText({ detail: 'Forbidden' })).toBeNull();
    expect(userTokenRequiredText({ detail: { code: 'status_change_blocked' } })).toBeNull();
    expect(userTokenRequiredText('Forbidden')).toBeNull();
    expect(serverErrorText({ detail: 'Forbidden' })).toBeNull();
  });
});

const outsideList = {
  detail: {
    code: 'tag_value_not_allowed',
    message: "Value 'secret' is not one of the possible values of tag 'classification'.",
    params: { tag: 'classification', value: 'secret', allowed: ['public', 'confidential'] },
  },
};

describe('tagValueNotAllowedText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('gives a value outside the possible values in the user language, with the allowed list', async () => {
    await i18n.changeLanguage('de');

    const german = tagValueNotAllowedText(outsideList);

    expect(german).toBe('"secret" ist kein zulässiger Wert für das Tag "classification". Zulässig: public, confidential.');
    expect(tagValueNotAllowedText(JSON.stringify(outsideList))).toBe(german);
    expect(serverErrorText(outsideList)).toBe(german);
  });

  it('is in English for an English user, and in every locale', async () => {
    await i18n.changeLanguage('en');
    expect(tagValueNotAllowedText(outsideList)).toBe(
      '"secret" is not an allowed value of tag "classification". Allowed: public, confidential.',
    );

    for (const language of ['de', 'en', 'es', 'fr', 'it', 'ja', 'nl', 'pt']) {
      await i18n.changeLanguage(language);
      expect(i18n.t('errors:tagValueNotAllowed', { value: 'v', tag: 't', allowed: 'a' })).not.toBe('errors:tagValueNotAllowed');
    }
  });

  it('gives nothing for any other error', () => {
    expect(tagValueNotAllowedText(body)).toBeNull();
    expect(tagValueNotAllowedText({ detail: { code: 'status_change_blocked', message: 'x' } })).toBeNull();
    expect(tagValueNotAllowedText({ detail: 'Value is not allowed' })).toBeNull();
    expect(tagValueNotAllowedText(null)).toBeNull();
  });
});
