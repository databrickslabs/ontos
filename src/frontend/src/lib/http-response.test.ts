import { describe, expect, it } from 'vitest';
import { readJsonResponse, responseErrorMessage } from './http-response';

const messages = {
  requestFailed: 'Could not complete the request.',
  validationFailed: 'Check the entered values.',
  invalidResponse: 'The server returned an invalid response.',
};

describe('HTTP response parsing', () => {
  it('returns JSON from a successful response', async () => {
    const response = new Response(JSON.stringify({ total: 12 }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });

    await expect(readJsonResponse(response, messages)).resolves.toEqual({ total: 12 });
  });

  it('surfaces a JSON API detail instead of masking it with a parser error', async () => {
    const response = new Response(JSON.stringify({ detail: 'Stored cost item is invalid' }), {
      status: 500,
      headers: { 'content-type': 'application/json' },
    });

    await expect(readJsonResponse(response, messages)).rejects.toThrow('Stored cost item is invalid');
  });

  it('does not expose a plain-text server error', async () => {
    const response = new Response('Internal Server Error', {
      status: 500,
      headers: { 'content-type': 'text/plain' },
    });

    await expect(readJsonResponse(response, messages)).rejects.toThrow(messages.requestFailed);
  });

  it('rejects a successful non-JSON response with a useful message', async () => {
    const response = new Response('<html>proxy response</html>', {
      status: 200,
      headers: { 'content-type': 'text/html' },
    });

    await expect(readJsonResponse(response, messages)).rejects.toThrow(messages.invalidResponse);
  });

  it('uses a safe validation message for FastAPI validation details', async () => {
    const response = new Response(
      JSON.stringify({ detail: [{ loc: ['body', 'cost_center'], msg: 'String should match pattern' }] }),
      { status: 422, headers: { 'content-type': 'application/json' } },
    );

    await expect(responseErrorMessage(response, messages)).resolves.toBe(messages.validationFailed);
  });

  it('falls back to the status when an error body is empty', async () => {
    const response = new Response(null, { status: 503 });

    await expect(responseErrorMessage(response, messages)).resolves.toBe(messages.requestFailed);
  });
});
