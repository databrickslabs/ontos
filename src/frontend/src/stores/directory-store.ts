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

import type { DirectoryStatus, Principal } from '@/types/directory';

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

  /**
   * Users of the Ontos teams the caller can read (GET /api/teams), the
   * picker's suggestions when it can't search the directory (#1618): a
   * non-admin gets 403 from /api/directory/*. null until loaded.
   */
  knownUsers: Principal[] | null;
  _knownUsersInflight: Promise<void> | null;

  fetchStatus: () => Promise<void>;
  /** Load `knownUsers` once per page; [] when the teams can't be read. */
  fetchKnownUsers: () => Promise<void>;
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

interface TeamMemberRow {
  member_type?: string;
  member_identifier?: string;
  member_name?: string | null;
}

interface TeamRow {
  name?: string;
  title?: string | null;
  members?: TeamMemberRow[];
}

/** The user members of `teams`, once each (case-insensitive), sorted by name. */
export function usersOfTeams(teams: TeamRow[]): Principal[] {
  const byId = new Map<string, Principal>();
  for (const team of teams) {
    for (const m of team.members ?? []) {
      const id = (m.member_identifier ?? '').trim();
      if (m.member_type !== 'user' || !id || byId.has(id.toLowerCase())) continue;
      const name = (m.member_name ?? '').trim();
      // The e-mail on row two only when the name row doesn't already show it
      byId.set(id.toLowerCase(), {
        type: 'user', id, display_name: name || id, sub_label: name ? id : null,
      });
    }
  }
  return Array.from(byId.values()).sort((a, b) => a.display_name.localeCompare(b.display_name));
}

async function loadKnownUsers(): Promise<Principal[]> {
  try {
    const res = await fetch('/api/teams');
    if (!res.ok) return [];
    const teams = await res.json();
    return Array.isArray(teams) ? usersOfTeams(teams) : [];
  } catch {
    return [];
  }
}

export const useDirectoryStore = create<DirectoryState>((set, get) => ({
  status: null,
  loaded: false,
  degraded: false,
  _inflight: null,
  knownUsers: null,
  _knownUsersInflight: null,

  fetchKnownUsers: async () => {
    const { knownUsers, _knownUsersInflight } = get();
    if (knownUsers) return;
    if (_knownUsersInflight) return _knownUsersInflight;
    const p = (async () => {
      const users = await loadKnownUsers();
      set({ knownUsers: users, _knownUsersInflight: null });
    })();
    set({ _knownUsersInflight: p });
    return p;
  },

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

  reset: () => set({
    status: null, loaded: false, degraded: false, _inflight: null,
    knownUsers: null, _knownUsersInflight: null,
  }),
}));
