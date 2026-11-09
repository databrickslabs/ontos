/**
 * Helpers for joining the Workflow Designer's role-token (selected
 * from the role Select) with the additional principals picked via
 * the PrincipalPicker ("Custom principals" toggle).
 *
 * The backend's recipient / approver resolver accepts a single
 * comma-separated string where each segment may be a role/literal
 * token, a user email, or a group name. ``joinRoleAndPrincipals``
 * produces that wire string; ``splitRoleAndPrincipals`` is its
 * inverse so the designer can hydrate the form from a persisted
 * config value.
 *
 * "Known" role tokens (``requester``, ``owner``, role UUIDs and
 * legacy aliases) are kept on the left side of the comma; anything
 * else on the right is treated as a principal pick.
 */

/**
 * Tokens we recognise as "role-shaped" rather than principal picks.
 * The legacy aliases mirror the backend's role_aliases map; the
 * ``looksLikeRoleUuid`` heuristic catches UUID-shaped tokens emitted
 * by the role Select.
 */
const KNOWN_ROLE_LITERALS = new Set([
  'requester',
  'owner',
  'domain_owners',
  'project_owners',
  'data_stewards',
  'admins',
]);

const UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

const normalizeRoleName = (s: string) => s.toLowerCase().replace(/[\s_]/g, '');

export interface NamedRole {
  id: string;
  name: string;
}

/**
 * Tokens the backend resolves from the entity's owners (``_OWNER_APPROVER_TOKENS``
 * in ``workflow_executor.py``). The role Select has an option for each, valued
 * with the canonical token; spellings the backend treats the same (compared
 * without case, spaces or underscores) are shown on that option.
 */
export const DOMAIN_OWNER_TOKEN = 'DomainOwner';
export const CONTRACT_APPROVER_TOKEN = 'ContractApprover';

const OWNER_TOKEN_BY_NORMALIZED: Record<string, string> = {
  domainowner: DOMAIN_OWNER_TOKEN,
  domainowners: DOMAIN_OWNER_TOKEN,
  contractapprover: CONTRACT_APPROVER_TOKEN,
};

function ownerOptionToken(token: string): string | undefined {
  return OWNER_TOKEN_BY_NORMALIZED[normalizeRoleName(token)];
}

function findRoleByName(token: string, roles: NamedRole[] | undefined): NamedRole | undefined {
  if (!roles || !token) return undefined;
  const wanted = normalizeRoleName(token);
  return roles.find((r) => normalizeRoleName(r.name) === wanted);
}

/**
 * Value to show in the role Select for a persisted role token. The shipped
 * workflows store role *names* (``DataSteward``) while the Select options are
 * keyed by role id, so a name is mapped to its option; anything else is kept.
 */
export function roleSelectValue(token: string, roles: NamedRole[] | undefined): string {
  return findRoleByName(token, roles)?.id ?? ownerOptionToken(token) ?? token;
}

function looksLikeRoleToken(token: string, roles?: NamedRole[]): boolean {
  if (!token) return false;
  if (findRoleByName(token, roles)) return true;
  if (ownerOptionToken(token)) return true;
  if (KNOWN_ROLE_LITERALS.has(token)) return true;
  if (token.startsWith('business:')) return true;
  if (UUID_RE.test(token)) return true;
  return false;
}

export function joinRoleAndPrincipals(
  roleToken: string | null | undefined,
  principals: string[],
): string {
  const segments: string[] = [];
  const seen = new Set<string>();

  const role = (roleToken || '').trim();
  if (role) {
    segments.push(role);
    seen.add(role);
  }
  for (const p of principals) {
    const v = p.trim();
    if (!v || seen.has(v)) continue;
    seen.add(v);
    segments.push(v);
  }
  return segments.join(',');
}

export interface SplitRecipients {
  roleToken: string;
  principals: string[];
}

export function splitRoleAndPrincipals(
  value: string | null | undefined,
  roles?: NamedRole[],
): SplitRecipients {
  const out: SplitRecipients = { roleToken: '', principals: [] };
  if (!value) return out;
  const segments = value.split(',').map((s) => s.trim()).filter(Boolean);
  for (const seg of segments) {
    if (!out.roleToken && looksLikeRoleToken(seg, roles)) {
      // First role-shaped token wins the slot; subsequent role-shaped
      // entries fall into the picker side so users can still see and
      // remove them.
      out.roleToken = seg;
    } else {
      out.principals.push(seg);
    }
  }
  return out;
}
