/**
 * Shared cache for the directory provider's wiring status.
 *
 * Every PrincipalPicker instance on a page consults this store so the
 * GET /api/directory/status call happens at most once per page load
 * regardless of how many pickers are mounted. Also tracks a
 * "degraded" flag: if a live search call fails mid-session, pickers
 * flip into manual-entry mode for the rest of the session and we
 * remember that decision here so newly mounted pickers don't probe
 * again.
 */

import { create } from 'zustand';

import type { DirectoryStatus } from '@/types/directory';

interface DirectoryState {
  status: DirectoryStatus | null;
  /** True once a fetch has resolved (success or failure). */
  loaded: boolean;
  /**
   * Set by pickers when a search call fails after status said
   * configured. Sticky for the lifetime of the page.
   */
  degraded: boolean;
  /** In-flight promise so concurrent pickers share one network call. */
  _inflight: Promise<void> | null;

  fetchStatus: () => Promise<void>;
  /** Force a re-fetch -- used by the Settings tab after Save. */
  refresh: () => Promise<void>;
  markDegraded: () => void;
  reset: () => void;
}

async function loadStatus(): Promise<DirectoryStatus | null> {
  try {
    const res = await fetch('/api/directory/status');
    if (!res.ok) {
      return { configured: false, provider_type: null, connection_name: null };
    }
    return (await res.json()) as DirectoryStatus;
  } catch {
    return { configured: false, provider_type: null, connection_name: null };
  }
}

export const useDirectoryStore = create<DirectoryState>((set, get) => ({
  status: null,
  loaded: false,
  degraded: false,
  _inflight: null,

  fetchStatus: async () => {
    const { loaded, _inflight } = get();
    if (loaded) return;
    if (_inflight) return _inflight;
    const p = (async () => {
      const status = await loadStatus();
      set({ status, loaded: true, _inflight: null });
    })();
    set({ _inflight: p });
    return p;
  },

  refresh: async () => {
    const p = (async () => {
      const status = await loadStatus();
      // ``refresh`` is called after a successful Save -- reset the
      // session-sticky ``degraded`` flag so the picker can probe again.
      set({ status, loaded: true, degraded: false, _inflight: null });
    })();
    set({ _inflight: p });
    return p;
  },

  markDegraded: () => set({ degraded: true }),

  reset: () => set({ status: null, loaded: false, degraded: false, _inflight: null }),
}));
