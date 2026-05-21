/**
 * Helpers shared by the Teams form, Data-product team-member, and
 * Data-contract team-member dialogs after their Phase 3 migration
 * onto ``PrincipalPicker``.
 *
 * Kept as pure functions so the integration logic is unit-testable
 * without mounting the Radix dialogs (which hang in jsdom in this
 * repo -- see the skipped ``team-form-dialog.test.tsx`` for context).
 */

import type { PrincipalType } from '@/types/directory';

/**
 * Narrow the picker's ``accepts`` filter based on the Teams row's
 * ``member_type``. ``user`` is the default; any value other than
 * ``group`` falls back to it so unrecognised future values are
 * handled gracefully.
 */
export function principalAcceptsForMemberType(
  memberType: string | null | undefined,
): Exclude<PrincipalType, 'unknown'>[] {
  return memberType === 'group' ? ['group'] : ['user'];
}

/**
 * Construct the ODCS-compatible team-member payload from the
 * data-contract dialog state. ODCS uses ``username``; the existing
 * backend still inspects ``email`` for backward compatibility, so we
 * populate both with the same picked principal id.
 */
export interface ContractTeamMemberInput {
  emailOrUsername: string;
  role: string;
  name?: string | null;
}

export interface ContractTeamMember {
  username: string;
  email: string;
  role: string;
  name?: string;
}

export function buildContractTeamMember(
  input: ContractTeamMemberInput,
): ContractTeamMember {
  const trimmed = input.emailOrUsername.trim();
  const name = input.name?.trim();
  return {
    username: trimmed,
    email: trimmed,
    role: input.role.trim(),
    ...(name ? { name } : {}),
  };
}
