/**
 * An error response carries its HTTP status, so callers can tell "no access"
 * (403) from "nothing found" (the Add Relationship dialog, #959 review).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useApi } from './use-api';

const respond = (status: number) => {
  (global.fetch as any).mockResolvedValueOnce({
    ok: false,
    status,
    headers: new Headers({ 'Content-Type': 'application/json' }),
    json: async () => ({ detail: 'Insufficient permissions' }),
  });
};

describe('useApi error status', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it('passes the status of an error response on for every method', async () => {
    const { result } = renderHook(() => useApi());

    respond(403);
    expect((await result.current.get('/api/x')).status).toBe(403);
    respond(404);
    expect((await result.current.post('/api/x', {})).status).toBe(404);
    respond(409);
    expect((await result.current.put('/api/x/1', {})).status).toBe(409);
    respond(422);
    expect((await result.current.patch('/api/x/1', {})).status).toBe(422);
    respond(403);
    expect((await result.current.delete('/api/x/1')).status).toBe(403);
  });
});
