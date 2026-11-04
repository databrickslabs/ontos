/**
 * A request that needs the user's Databricks token and has none is answered
 * with 403 `{detail: {code: 'user_token_required', message}}`. useApi shows it
 * in the user's language and passes the code on.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import i18n from '@/i18n/config';
import { useApi } from './use-api';

const ENGLISH = "This request needs the user's Databricks token, and it has none.";
const refused = { detail: { code: 'user_token_required', message: ENGLISH, params: {} } };

const respond = (status: number, body: unknown) => {
  (global.fetch as any).mockResolvedValueOnce({
    ok: false,
    status,
    headers: new Headers({ 'Content-Type': 'application/json' }),
    json: async () => body,
  });
};

describe('useApi with a request refused for a missing user token', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('shows it in the user language for every method and passes the code on', async () => {
    await i18n.changeLanguage('pt');
    const portuguese = i18n.t('errors:userTokenRequired');
    expect(portuguese).toContain('token de acesso do Databricks');
    const { result } = renderHook(() => useApi());

    respond(403, refused);
    const response = await result.current.get('/api/data-asset-reviews/r-1/assets/a-1/preview');
    expect(response.error).toBe(portuguese);
    expect(response.errorCode).toBe('user_token_required');
    respond(403, refused);
    expect((await result.current.post('/api/data-asset-reviews', {})).error).toBe(portuguese);
    respond(403, refused);
    expect((await result.current.put('/api/x/1', {})).error).toBe(portuguese);
    respond(403, refused);
    expect((await result.current.patch('/api/x/1', {})).error).toBe(portuguese);
    respond(403, refused);
    expect((await result.current.delete('/api/x/1')).error).toBe(portuguese);
  });

  it('keeps the text of another forbidden error', async () => {
    await i18n.changeLanguage('pt');
    respond(403, { detail: 'Catalog not allowed by sandbox policy' });
    const { result } = renderHook(() => useApi());

    const response = await result.current.post('/api/self-service/create', {});

    expect(response.error).toBe('Catalog not allowed by sandbox policy');
  });
});
