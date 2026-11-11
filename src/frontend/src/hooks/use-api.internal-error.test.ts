/**
 * An unexpected server error is answered as `{detail, code: 'internal_error',
 * params: {errorId}}` (the backend keeps the exception's text in its log).
 * useApi shows it in the user's language, with the error id, and passes the
 * code on; other errors keep their text.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import i18n from '@/i18n/config';
import { useApi } from './use-api';

const ENGLISH = 'An unexpected error occurred. The details are in the server log (error id 3f2a9c81d0be).';

const respond = (status: number, body: unknown) => {
  (global.fetch as any).mockResolvedValueOnce({
    ok: false,
    status,
    headers: new Headers({ 'Content-Type': 'application/json' }),
    json: async () => body,
  });
};

const internalError = { detail: ENGLISH, code: 'internal_error', params: { errorId: '3f2a9c81d0be' } };

describe('useApi with an unexpected server error', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('shows the generic text with its error id and passes the code on', async () => {
    respond(500, internalError);
    const { result } = renderHook(() => useApi());

    const response = await result.current.post('/api/data-products', { name: 'x' });

    expect(response.error).toBe(ENGLISH);
    expect(response.errorCode).toBe('internal_error');
    expect(response.errorParams).toEqual({ errorId: '3f2a9c81d0be' });
  });

  it('shows it in the user language for every method', async () => {
    await i18n.changeLanguage('pt');
    const { result } = renderHook(() => useApi());
    const portuguese =
      'Ocorreu um erro inesperado. Os detalhes estão no log do servidor (id do erro 3f2a9c81d0be).';

    respond(500, internalError);
    expect((await result.current.get('/api/data-contracts')).error).toBe(portuguese);
    respond(500, internalError);
    expect((await result.current.post('/api/data-products', {})).error).toBe(portuguese);
    respond(500, internalError);
    expect((await result.current.put('/api/data-products/p-1', {})).error).toBe(portuguese);
    respond(500, internalError);
    expect((await result.current.delete('/api/data-products/p-1')).error).toBe(portuguese);
  });

  it('keeps the text of any other error', async () => {
    await i18n.changeLanguage('pt');
    respond(500, { detail: 'Failed to create contract' });
    const { result } = renderHook(() => useApi());

    const response = await result.current.post('/api/data-contracts', {});

    expect(response.error).toBe('Failed to create contract');
    expect(response.errorCode).toBeNull();
  });
});
