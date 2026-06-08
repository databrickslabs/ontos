import { describe, it, expect } from 'vitest';
import { ApprovalEntity, AppRole, FeatureAccessLevel } from '@/types/settings';
import { ACCESS_LEVEL_ORDER, userHasApprovalPrivilege } from './permissions';

function role(partial: Partial<AppRole>): AppRole {
  return {
    id: 'r1',
    name: 'Role',
    assigned_groups: [],
    feature_permissions: {},
    ...partial,
  } as AppRole;
}

describe('permissions', () => {
  describe('ACCESS_LEVEL_ORDER', () => {
    it('ranks access levels from none up to admin', () => {
      expect(ACCESS_LEVEL_ORDER[FeatureAccessLevel.NONE]).toBe(0);
      expect(ACCESS_LEVEL_ORDER[FeatureAccessLevel.ADMIN]).toBe(5);
      expect(ACCESS_LEVEL_ORDER[FeatureAccessLevel.READ_WRITE]).toBeGreaterThan(
        ACCESS_LEVEL_ORDER[FeatureAccessLevel.READ_ONLY],
      );
    });
  });

  describe('userHasApprovalPrivilege', () => {
    const roles: AppRole[] = [
      role({
        id: 'stewards',
        assigned_groups: ['Data-Stewards'],
        approval_privileges: { [ApprovalEntity.CONTRACTS]: true },
      }),
      role({
        id: 'viewers',
        assigned_groups: ['viewers'],
        approval_privileges: { [ApprovalEntity.CONTRACTS]: false },
      }),
    ];

    it('uses the applied role override when provided', () => {
      expect(userHasApprovalPrivilege(ApprovalEntity.CONTRACTS, [], roles, 'stewards')).toBe(true);
      expect(userHasApprovalPrivilege(ApprovalEntity.CONTRACTS, [], roles, 'viewers')).toBe(false);
      expect(userHasApprovalPrivilege(ApprovalEntity.CONTRACTS, [], roles, 'missing')).toBe(false);
    });

    it('grants when the user is in a matching role group (case-insensitive)', () => {
      expect(userHasApprovalPrivilege(ApprovalEntity.CONTRACTS, ['data-stewards'], roles, null)).toBe(
        true,
      );
    });

    it('denies when no group matches', () => {
      expect(userHasApprovalPrivilege(ApprovalEntity.CONTRACTS, ['randoms'], roles, null)).toBe(false);
    });

    it('denies when the matching role lacks the privilege', () => {
      expect(userHasApprovalPrivilege(ApprovalEntity.CONTRACTS, ['viewers'], roles, null)).toBe(false);
    });

    it('handles nullish user groups', () => {
      expect(userHasApprovalPrivilege(ApprovalEntity.CONTRACTS, null, roles, null)).toBe(false);
      expect(userHasApprovalPrivilege(ApprovalEntity.CONTRACTS, undefined, roles, null)).toBe(false);
    });
  });
});
