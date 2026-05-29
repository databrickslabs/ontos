/**
 * Audience token helpers for the comment composer.
 *
 * Audience tokens flow on the wire as a single ``string[]`` mixing
 * four shapes:
 *
 * - ``team:<team-id>`` — selected from the Teams checkbox list.
 * - ``role_id:<uuid>`` — NEW canonical format (issue #326). Role selected
 *   via the App Roles checkbox list in the composer; persisted on save.
 * - ``role:<role-name>`` — LEGACY format still present in existing rows.
 *   Parsed on read and hydrated back into the role picker by resolving
 *   the name against the available roles list. Not emitted by the
 *   composer on save (round-trip identity is preserved on edit — legacy
 *   tokens are only rewritten when the user explicitly changes the
 *   audience selection).
 * - anything else — a Directory principal (plain user email/UPN or
 *   plain group display name) picked via the PrincipalPicker.
 *
 * These helpers keep the round-trip (compose -> store -> edit) honest
 * across the four shapes and are pure functions so they can be unit
 * tested without rendering Radix UI.
 */

export interface ParsedAudience {
  teams: string[];
  /**
   * Role UUIDs (from ``role_id:<uuid>`` tokens) or legacy role names
   * (from ``role:<name>`` tokens). The caller must distinguish using
   * ``legacyRoleNames`` if it needs to resolve names to IDs.
   */
  roleIds: string[];
  /** Legacy ``role:<name>`` tokens that could not be resolved to a UUID. */
  legacyRoleNames: string[];
  principals: string[];
}

const TEAM_PREFIX = 'team:';
const ROLE_ID_PREFIX = 'role_id:';
const LEGACY_ROLE_PREFIX = 'role:';

/**
 * Parse a raw audience token array into its four constituent parts.
 *
 * @param audience - raw audience token list from the API
 * @param rolesByName - optional lookup map from role name → UUID, used to
 *   upgrade ``role:<name>`` tokens to ``roleIds`` when the name resolves.
 */
export function parseAudienceTokens(
  audience: string[] | null | undefined,
  rolesByName?: Record<string, string>,
): ParsedAudience {
  const out: ParsedAudience = {
    teams: [],
    roleIds: [],
    legacyRoleNames: [],
    principals: [],
  };
  if (!audience) return out;
  for (const token of audience) {
    if (typeof token !== 'string' || token.length === 0) continue;
    if (token.startsWith(TEAM_PREFIX)) {
      out.teams.push(token.slice(TEAM_PREFIX.length));
    } else if (token.startsWith(ROLE_ID_PREFIX)) {
      out.roleIds.push(token.slice(ROLE_ID_PREFIX.length));
    } else if (token.startsWith(LEGACY_ROLE_PREFIX)) {
      const name = token.slice(LEGACY_ROLE_PREFIX.length);
      const resolvedId = rolesByName?.[name];
      if (resolvedId) {
        out.roleIds.push(resolvedId);
      } else {
        out.legacyRoleNames.push(name);
      }
    } else {
      out.principals.push(token);
    }
  }
  return out;
}

/**
 * Build a token array from the parsed audience parts.
 *
 * Roles are always emitted as ``role_id:<uuid>`` — the canonical format.
 * Legacy role names are passed through unchanged to preserve round-trip
 * identity for rows that were not re-saved by the user.
 */
export function buildAudienceTokens(parsed: ParsedAudience): string[] {
  return [
    ...parsed.teams.map((t) => `${TEAM_PREFIX}${t}`),
    ...parsed.roleIds.map((id) => `${ROLE_ID_PREFIX}${id}`),
    // Preserve legacy tokens that could not be resolved to a UUID
    ...parsed.legacyRoleNames.map((n) => `${LEGACY_ROLE_PREFIX}${n}`),
    ...parsed.principals,
  ];
}

/**
 * Resolve a ``role_id:<uuid>`` or ``role:<name>`` token to a human-readable
 * display name.
 *
 * @param token - raw audience token string
 * @param rolesById - map from role UUID → display name
 * @returns display name, or ``null`` if the token is not a role token
 */
export function resolveRoleTokenLabel(
  token: string,
  rolesById: Record<string, string>,
): string | null {
  if (token.startsWith(ROLE_ID_PREFIX)) {
    const uuid = token.slice(ROLE_ID_PREFIX.length);
    return rolesById[uuid] ?? `Role (${uuid.slice(0, 8)}…)`;
  }
  if (token.startsWith(LEGACY_ROLE_PREFIX)) {
    return token.slice(LEGACY_ROLE_PREFIX.length);
  }
  return null;
}
