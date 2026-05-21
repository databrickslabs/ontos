/**
 * Audience token helpers for the comment composer.
 *
 * Audience tokens flow on the wire as a single ``string[]`` mixing
 * three shapes:
 *
 * - ``team:<team-id>`` — selected from the Teams checkbox list.
 * - ``role:<role-name>`` — selected from the App Roles checkbox list.
 * - anything else — a Directory principal (plain user email/UPN or
 *   plain group display name) picked via the PrincipalPicker.
 *
 * These helpers keep the round-trip (compose -> store -> edit) honest
 * across the three shapes and are pure functions so they can be unit
 * tested without rendering Radix UI.
 */

export interface ParsedAudience {
  teams: string[];
  roles: string[];
  principals: string[];
}

const TEAM_PREFIX = 'team:';
const ROLE_PREFIX = 'role:';

export function parseAudienceTokens(
  audience: string[] | null | undefined,
): ParsedAudience {
  const out: ParsedAudience = { teams: [], roles: [], principals: [] };
  if (!audience) return out;
  for (const token of audience) {
    if (typeof token !== 'string' || token.length === 0) continue;
    if (token.startsWith(TEAM_PREFIX)) {
      out.teams.push(token.slice(TEAM_PREFIX.length));
    } else if (token.startsWith(ROLE_PREFIX)) {
      out.roles.push(token.slice(ROLE_PREFIX.length));
    } else {
      out.principals.push(token);
    }
  }
  return out;
}

export function buildAudienceTokens(parsed: ParsedAudience): string[] {
  return [
    ...parsed.teams.map((t) => `${TEAM_PREFIX}${t}`),
    ...parsed.roles.map((r) => `${ROLE_PREFIX}${r}`),
    ...parsed.principals,
  ];
}
