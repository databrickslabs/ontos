import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { estateErrorText } from './estate-error';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('estateErrorText', () => {
  it('translates a duplicate estate name with its parameters', async () => {
    await i18n.changeLanguage('pt');
    const text = estateErrorText(
      { error: "An estate named 'EU' already exists.", errorCode: 'estate_name_conflict', errorParams: { name: 'EU' } },
      i18n.t,
    );
    expect(text).toBe('Já existe um estate chamado "EU".');
  });

  it('falls back to the server message for other errors', () => {
    expect(estateErrorText({ error: 'Failed to create estate', errorCode: null }, i18n.t)).toBe('Failed to create estate');
    expect(estateErrorText({ error: 'Boom', errorCode: 'something_else' }, i18n.t)).toBe('Boom');
  });
});
