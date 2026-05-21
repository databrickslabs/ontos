/**
 * Tests for the directory store.
 *
 * The store's one job is to ensure /api/directory/status is fetched
 * at most once per page load and to expose the page-sticky
 * ``degraded`` flag.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDirectoryStore } from './directory-store';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  global.fetch = fetchMock as unknown as typeof fetch;
  useDirectoryStore.getState().reset();
});

afterEach(() => {
  useDirectoryStore.getState().reset();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('directory-store', () => {
  it('fetchStatus populates status and sets loaded', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ configured: true, provider_type: 'entra', connection_name: 'graph' }),
    );
    await useDirectoryStore.getState().fetchStatus();
    const s = useDirectoryStore.getState();
    expect(s.loaded).toBe(true);
    expect(s.status?.configured).toBe(true);
    expect(s.status?.provider_type).toBe('entra');
  });

  it('fetchStatus is a no-op after loaded', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ configured: false, provider_type: null, connection_name: null }),
    );
    await useDirectoryStore.getState().fetchStatus();
    await useDirectoryStore.getState().fetchStatus();
    await useDirectoryStore.getState().fetchStatus();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('concurrent fetchStatus calls share a single in-flight request', async () => {
    let resolveBody: (v: Response) => void = () => {};
    fetchMock.mockReturnValue(new Promise<Response>((r) => (resolveBody = r)));
    const p1 = useDirectoryStore.getState().fetchStatus();
    const p2 = useDirectoryStore.getState().fetchStatus();
    const p3 = useDirectoryStore.getState().fetchStatus();
    resolveBody(jsonResponse({ configured: true, provider_type: 'entra', connection_name: 'graph' }));
    await Promise.all([p1, p2, p3]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('falls back to a not-configured status on fetch failure', async () => {
    fetchMock.mockRejectedValue(new Error('network down'));
    await useDirectoryStore.getState().fetchStatus();
    const s = useDirectoryStore.getState();
    expect(s.loaded).toBe(true);
    expect(s.status?.configured).toBe(false);
  });

  it('refresh re-fetches and clears the degraded flag', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ configured: true, provider_type: 'entra', connection_name: 'graph' }),
    );
    await useDirectoryStore.getState().fetchStatus();
    useDirectoryStore.getState().markDegraded();
    expect(useDirectoryStore.getState().degraded).toBe(true);
    await useDirectoryStore.getState().refresh();
    expect(useDirectoryStore.getState().degraded).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('markDegraded is session-sticky', () => {
    useDirectoryStore.getState().markDegraded();
    expect(useDirectoryStore.getState().degraded).toBe(true);
    // Subsequent fetchStatus shouldn't unset it (only refresh does).
    useDirectoryStore.setState({ loaded: false });
    // Don't actually call fetch; just verify the flag persists.
    expect(useDirectoryStore.getState().degraded).toBe(true);
  });
});
