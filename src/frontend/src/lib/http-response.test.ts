import { describe, expect, it } from 'vitest';
import { readJsonResponse, responseErrorMessage } from './http-response';

describe('HTTP response parsing', () => {
  it('returns JSON from a successful response', async () => {
    const response = new Response(JSON.stringify({ total: 12 }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });

    await expect(readJsonResponse(response)).resolves.toEqual({ total: 12 });
  });

  it('surfaces a JSON API detail instead of masking it with a parser error', async () => {
    const response = new Response(JSON.stringify({ detail: 'Stored cost item is invalid' }), {
      status: 500,
      headers: { 'content-type': 'application/json' },
    });

    await expect(readJsonResponse(response)).rejects.toThrow('Stored cost item is invalid');
  });

  it('surfaces a plain-text server error', async () => {
    const response = new Response('Internal Server Error', {
      status: 500,
      headers: { 'content-type': 'text/plain' },
    });

    await expect(readJsonResponse(response)).rejects.toThrow('Internal Server Error');
  });

  it('rejects a successful non-JSON response with a useful message', async () => {
    const response = new Response('<html>proxy response</html>', {
      status: 200,
      headers: { 'content-type': 'text/html' },
    });

    await expect(readJsonResponse(response)).rejects.toThrow('Expected a JSON response (200)');
  });

  it('falls back to the status when an error body is empty', async () => {
    const response = new Response(null, { status: 503 });

    await expect(responseErrorMessage(response)).resolves.toBe('Request failed (503)');
  });
});
