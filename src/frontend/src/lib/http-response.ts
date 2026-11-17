function detailText(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return null;
}

export async function responseErrorMessage(response: Response): Promise<string> {
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (contentType.includes('application/json')) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const message = detailText(body?.detail);
    if (message) return message;
  } else {
    const text = await response.text().catch(() => '');
    if (text.trim()) return text.trim();
  }
  return `Request failed (${response.status})`;
}

export async function readJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(await responseErrorMessage(response));
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (!contentType.includes('application/json')) {
    throw new Error(`Expected a JSON response (${response.status})`);
  }
  return response.json() as Promise<T>;
}
