export type HttpResponseMessages = {
  requestFailed: string;
  validationFailed: string;
  invalidResponse: string;
};

function detailText(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return null;
}

export async function responseErrorMessage(
  response: Response,
  messages: HttpResponseMessages,
): Promise<string> {
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (contentType.includes('application/json')) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const message = detailText(body?.detail);
    if (message) return message;
    if (Array.isArray(body?.detail)) return messages.validationFailed;
  }
  return messages.requestFailed;
}

export async function readJsonResponse<T>(
  response: Response,
  messages: HttpResponseMessages,
): Promise<T> {
  if (!response.ok) throw new Error(await responseErrorMessage(response, messages));
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (!contentType.includes('application/json')) {
    throw new Error(messages.invalidResponse);
  }
  return response.json() as Promise<T>;
}
