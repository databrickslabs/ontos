import { create } from 'zustand';

/**
 * Test-persona override store.
 *
 * When the backend exposes `GET /api/test/personas` (i.e. `TEST_USER_TOKEN`
 * is configured server-side), this store hydrates the persona list and lets
 * the user pick one. A global `fetch` interceptor (installed in `app.tsx`)
 * consults `getActiveOverride()` on every request to inject the
 * `X-Test-Token`, `X-Test-User-Email`, and `X-Test-User-Groups` headers.
 *
 * The token itself never travels server -> client. It's read from
 * `import.meta.env.VITE_TEST_USER_TOKEN` (or, when not running through Vite,
 * from `localStorage['ucapp.testToken']` so a tester can paste it in).
 */

export interface TestPersona {
  id: string;
  label: string;
  email: string;
  groups: string[] | null;
  description?: string;
}

export interface TestPersonaHeaders {
  token: string;
  email: string;
  groups: string;
  username: string;
  name: string;
  ip: string;
}

interface TestPersonasResponse {
  personas: TestPersona[];
  headers: TestPersonaHeaders;
}

interface TestPersonaState {
  /** True when the backend reports the feature is enabled. */
  enabled: boolean;
  /** True while the initial probe / persona fetch is in flight. */
  isLoading: boolean;
  /** Loaded once at startup; null until probe completes. */
  personas: TestPersona[];
  /** Selected persona id (persisted in localStorage). */
  selectedPersonaId: string | null;
  /** Token to send in `X-Test-Token`. Null when not configured. */
  token: string | null;
  /** Server-provided header names so client and server stay in sync. */
  headerNames: TestPersonaHeaders | null;
  /** Probe + load personas. Safe to call multiple times. */
  initialize: () => Promise<void>;
  /** Select a persona and persist. Pass null to clear. */
  setPersona: (id: string | null) => void;
  /** Convenience accessor. */
  getActivePersona: () => TestPersona | null;
}

const STORAGE_KEY_PERSONA = 'ucapp.testPersonaId';
const STORAGE_KEY_TOKEN = 'ucapp.testToken';

const readToken = (): string | null => {
  // Prefer the Vite-injected env var so the token is provisioned out of band.
  // Fall back to localStorage for ad-hoc testers (no Vite build).
  const fromEnv =
    typeof import.meta !== 'undefined' &&
    (import.meta as any).env &&
    ((import.meta as any).env.VITE_TEST_USER_TOKEN as string | undefined);
  if (fromEnv) return fromEnv;
  try {
    return localStorage.getItem(STORAGE_KEY_TOKEN);
  } catch {
    return null;
  }
};

const useTestPersonaStore = create<TestPersonaState>((set, get) => ({
  enabled: false,
  isLoading: false,
  personas: [],
  selectedPersonaId: null,
  token: null,
  headerNames: null,

  initialize: async () => {
    if (get().isLoading || get().enabled) return;
    set({ isLoading: true });
    try {
      const response = await fetch('/api/test/personas', { cache: 'no-store' });
      if (response.status === 404) {
        // Feature disabled server-side. Clear any stale selection.
        set({
          enabled: false,
          personas: [],
          selectedPersonaId: null,
          token: null,
          headerNames: null,
        });
        try {
          localStorage.removeItem(STORAGE_KEY_PERSONA);
        } catch {
          /* ignore */
        }
        return;
      }
      if (!response.ok) {
        console.warn('[test-persona-store] Unexpected status from /api/test/personas:', response.status);
        return;
      }
      const data: TestPersonasResponse = await response.json();
      const token = readToken();
      let stored: string | null = null;
      try {
        stored = localStorage.getItem(STORAGE_KEY_PERSONA);
      } catch {
        /* ignore */
      }
      // Validate stored selection still exists.
      const validSelection =
        stored && data.personas.some((p) => p.id === stored) ? stored : null;
      set({
        enabled: true,
        personas: data.personas,
        headerNames: data.headers,
        token,
        selectedPersonaId: validSelection,
      });
      if (token && validSelection) {
        const p = data.personas.find((x) => x.id === validSelection);
        console.warn(
          `[test-persona-store] Restored test persona "${p?.label}" (${p?.email}). All API requests will impersonate this user.`,
        );
      } else if (!token) {
        console.info(
          '[test-persona-store] Test personas available, but no token configured (VITE_TEST_USER_TOKEN or localStorage["ucapp.testToken"]). Set a token to enable impersonation.',
        );
      }
    } catch (e) {
      // Network error / endpoint missing: leave disabled.
      console.debug('[test-persona-store] Probe failed (feature likely disabled):', e);
    } finally {
      set({ isLoading: false });
    }
  },

  setPersona: (id) => {
    const state = get();
    if (!state.enabled) return;
    if (id === null) {
      try {
        localStorage.removeItem(STORAGE_KEY_PERSONA);
      } catch {
        /* ignore */
      }
      set({ selectedPersonaId: null });
      return;
    }
    if (!state.personas.some((p) => p.id === id)) {
      console.warn(`[test-persona-store] Unknown persona id "${id}"; ignoring.`);
      return;
    }
    try {
      localStorage.setItem(STORAGE_KEY_PERSONA, id);
    } catch {
      /* ignore */
    }
    set({ selectedPersonaId: id });
  },

  getActivePersona: () => {
    const { personas, selectedPersonaId } = get();
    if (!selectedPersonaId) return null;
    return personas.find((p) => p.id === selectedPersonaId) || null;
  },
}));

/**
 * Snapshot-style accessor used by the global fetch interceptor.
 * Reads from the store outside React (no hook required).
 */
export interface ActiveOverride {
  token: string;
  email: string;
  groups: string[];
  headerNames: TestPersonaHeaders;
}

export function getActiveOverride(): ActiveOverride | null {
  const { enabled, token, selectedPersonaId, personas, headerNames } =
    useTestPersonaStore.getState();
  if (!enabled || !token || !selectedPersonaId || !headerNames) return null;
  const persona = personas.find((p) => p.id === selectedPersonaId);
  if (!persona) return null;
  return {
    token,
    email: persona.email,
    groups: persona.groups || [],
    headerNames,
  };
}

/**
 * Monkeypatch `window.fetch` once at app startup so every request
 * automatically carries the test override headers when a persona is active.
 *
 * The interceptor is a no-op when the feature isn't enabled or no persona is
 * selected, so it's safe to install unconditionally in production builds
 * (the backend would ignore the headers without `TEST_USER_TOKEN` anyway).
 */
export function installTestPersonaFetchInterceptor(): void {
  if (typeof window === 'undefined') return;
  const w = window as any;
  if (w.__testPersonaFetchInstalled) return;
  w.__testPersonaFetchInstalled = true;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const override = getActiveOverride();
    if (!override) {
      return original(input, init);
    }
    // Only inject for same-origin /api requests so we don't leak headers
    // to third-party endpoints (LLM streaming, telemetry, etc.).
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.toString()
          : (input as Request).url;
    if (!url.startsWith('/api') && !url.startsWith(window.location.origin + '/api')) {
      return original(input, init);
    }
    const merged = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
    merged.set(override.headerNames.token, override.token);
    merged.set(override.headerNames.email, override.email);
    // Always send the groups header (even when empty) so the backend doesn't
    // fall through to a SCIM lookup the tester didn't ask for.
    merged.set(override.headerNames.groups, JSON.stringify(override.groups));
    return original(input, { ...init, headers: merged });
  };
}

export default useTestPersonaStore;
