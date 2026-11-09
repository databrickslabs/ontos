import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { internalErrorText } from './server-error-text';

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
