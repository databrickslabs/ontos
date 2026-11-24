import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * #1609: with test personas on, an /api request sent before
 * GET /api/test/personas resolves must not go out as the real user.
 */

const HEADERS = {
  token: 'X-Test-Token',
  email: 'X-Test-User-Email',
  groups: 'X-Test-User-Groups',
  username: 'X-Test-User-Username',
  name: 'X-Test-User-Name',
  ip: 'X-Test-User-Ip',
};

const PERSONAS = {
  personas: [
    { id: 'consumer', label: 'Data Consumer', email: 'consumer@test.local', groups: ['consumers'] },
  ],
  headers: HEADERS,
};

type Deferred = { resolve: (r: Response) => void; promise: Promise<Response> };

function deferred(): Deferred {
  let resolve!: (r: Response) => void;
  const promise = new Promise<Response>((r) => {
    resolve = r;
  });
  return { resolve, promise };
}

function headerOf(init: RequestInit | undefined, name: string): string | null {
  return new Headers(init?.headers).get(name);
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('test persona fetch interceptor', () => {
  let probe: Deferred;
  let underlying: ReturnType<typeof vi.fn>;
  const realFetch = window.fetch;

  beforeEach(() => {
    vi.resetModules();
    delete (window as any).__testPersonaFetchInstalled;
    localStorage.setItem('ucapp.testToken', 'secret');
    localStorage.setItem('ucapp.testPersonaId', 'consumer');
    probe = deferred();
    underlying = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : String(input);
      if (url.startsWith('/api/test/personas')) return probe.promise;
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    window.fetch = underlying as unknown as typeof window.fetch;
  });

  afterEach(() => {
    window.fetch = realFetch;
    delete (window as any).__testPersonaFetchInstalled;
    localStorage.clear();
  });

  async function install() {
    const mod = await import('./test-persona-store');
    mod.installTestPersonaFetchInterceptor();
    return mod;
  }

  it('holds an early /api request until the personas resolve, then sends the persona', async () => {
    await install();

    const early = window.fetch('/api/notifications');
    await flush();
    // Only the probe went out; the early request waits.
    const sentUrls = underlying.mock.calls.map((c) => String(c[0]));
    expect(sentUrls).toEqual(['/api/test/personas']);

    probe.resolve(new Response(JSON.stringify(PERSONAS), { status: 200 }));
    await early;

    const call = underlying.mock.calls.find((c) => String(c[0]) === '/api/notifications');
    expect(call).toBeDefined();
    expect(headerOf(call![1], 'X-Test-User-Email')).toBe('consumer@test.local');
    expect(headerOf(call![1], 'X-Test-Token')).toBe('secret');
  });

  it('shares one probe between the interceptor and initialize', async () => {
    const mod = await install();
    const early = window.fetch('/api/user/details');
    const init = mod.default.getState().initialize();
    probe.resolve(new Response(JSON.stringify(PERSONAS), { status: 200 }));
    await Promise.all([early, init]);

    const probes = underlying.mock.calls.filter((c) => String(c[0]) === '/api/test/personas');
    expect(probes).toHaveLength(1);
  });

  it('sends requests without headers once the feature reports disabled', async () => {
    await install();
    const early = window.fetch('/api/user/details');
    probe.resolve(new Response('', { status: 404 }));
    await early;
    const later = window.fetch('/api/user/permissions');
    await later;

    for (const url of ['/api/user/details', '/api/user/permissions']) {
      const call = underlying.mock.calls.find((c) => String(c[0]) === url);
      expect(call).toBeDefined();
      expect(headerOf(call![1], 'X-Test-Token')).toBeNull();
    }
  });

  it('holds nothing when no test token is stored (production)', async () => {
    localStorage.removeItem('ucapp.testToken');
    await install();
    await window.fetch('/api/user/details');
    // Sent at once, and no probe was started by the interceptor
    expect(underlying.mock.calls.map((c) => String(c[0]))).toEqual(['/api/user/details']);
  });

  it('ends the hold after PROBE_HOLD_MS when the probe hangs', async () => {
    vi.useFakeTimers();
    try {
      const mod = await install();
      const early = window.fetch('/api/notifications');
      await vi.advanceTimersByTimeAsync(mod.PROBE_HOLD_MS - 1);
      expect(underlying.mock.calls.map((c) => String(c[0]))).toEqual(['/api/test/personas']);
      await vi.advanceTimersByTimeAsync(1);
      await early;
      const call = underlying.mock.calls.find((c) => String(c[0]) === '/api/notifications');
      expect(call).toBeDefined();
      // No persona known yet: sent without headers rather than never
      expect(headerOf(call![1], 'X-Test-Token')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not hold non-API requests', async () => {
    await install();
    await window.fetch('https://example.com/telemetry');
    expect(underlying.mock.calls.map((c) => String(c[0]))).toEqual([
      'https://example.com/telemetry',
    ]);
  });
});
