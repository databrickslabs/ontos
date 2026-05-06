# PRD: Individual User Assignment to App Roles

## Problem Statement

App Roles can only be assigned to Databricks groups via the `assigned_groups` field. To give a single user a specific role, an administrator must create or modify a Databricks group externally, add the user to it, then assign that group to the App Role. This creates unnecessary overhead for ad-hoc assignments, makes testing role behavior slow, prevents fine-grained targeting (e.g., giving one engineer Data Steward access for a sprint without promoting their entire team), and leaves a gap in the RBAC model since the authorization system already has access to `user_details.email` but only uses group membership for role matching.

## Solution

Add a parallel `assigned_users` field (list of user email strings) to App Roles that works alongside `assigned_groups`. A role matches a user if:

- The user's groups intersect with the role's `assigned_groups` (existing behavior), **OR**
- The user's email is in the role's `assigned_users` (new behavior)

This is purely additive — no existing behavior changes. The implementation mirrors the `assigned_groups` pattern (JSON text column, same serialization, same case-insensitive matching).

The roles table column currently labeled "Assigned Groups" is renamed to "Principals" and displays both groups and users as differentiated badges, following the same visual pattern used in the Teams view (User icon + light badge for users, Users icon + dark badge for groups).

Both the groups and users inputs in the role form dialog are upgraded to a badge-with-X-to-remove pattern, replacing the current comma-separated text input for groups.

## User Stories

1. As an **Admin**, I want to assign an App Role directly to a specific user by email, so that I can grant them permissions without creating or modifying a Databricks group.
2. As an **Admin**, I want to see both assigned groups and assigned users displayed together in a "Principals" column in the Roles table, so that I can audit all role assignments at a glance.
3. As an **Admin**, I want groups and users to be visually differentiated in the Principals column (group icon + dark badge for groups, user icon + light badge for users), so that I can immediately tell them apart — matching the pattern already used in the Teams view.
4. As an **Admin**, I want to add and remove individual users in the role form dialog using a badge-with-X pattern, so that managing assignments is quick and precise.
5. As an **Admin**, I want the groups input in the role form dialog also upgraded to the badge-with-X pattern (replacing comma-separated text), so that both principal types have a consistent UX.
6. As an **Admin**, I want to assign individual users to the Admin role via email, so that admin access is not limited to group-based assignment.
7. As a **User** assigned directly via email, I want to receive the same permissions as if I were in an assigned group, so that my experience is identical regardless of how I was assigned.
8. As a **User** with no group memberships but directly assigned to a role, I want to still be able to use the app, so that direct assignment works as a standalone mechanism (not just a supplement to groups).
9. As an **Admin**, I want existing group-based assignments to continue working exactly as before, so that adding user-level assignment doesn't break anything.
10. As an **Admin**, I want the "Request Access" button in the roles table to correctly reflect that I already have a role when I'm assigned via email (not just via group), so that the UI state is accurate.

## Implementation Decisions

### User Identifier

Email address is the identifier, matching the existing `user_details.email` field already available in every authorization check. Matching is case-insensitive (`.lower()` on both sides), consistent with how group matching works today.

### OR Semantics

Role matches if user is in `assigned_groups` OR in `assigned_users`. These are additive. If a user matches multiple roles (via groups and/or direct assignment), permissions are merged by taking the highest level per feature — same as today.

### No-Groups Guard Relaxation

Currently, `PermissionChecker` denies access if `user_details.groups` is empty (hard 403). This guard must be relaxed: a user with no groups but a direct email assignment must be allowed through. The check changes from "has groups?" to "has groups OR has email that might match a role?".

### Storage Pattern

New `assigned_users` column on `app_roles` table, stored as JSON text (`Text` column, default `'[]'`), identical to `assigned_groups`. No junction table.

### Alembic Migration

Single migration adding the column. Revises the current head (`d1_odcs_v310_full_persistence`).

### Backend Authorization Flow

`get_user_effective_permissions()` gains an optional `user_email` parameter. The role matching loop checks both group intersection AND email membership. The email is threaded through from `PermissionChecker` and `ApprovalChecker` (which already have access to `user_details.email`) into the authorization manager.

### Combined "Principals" Column

The roles table replaces the "Assigned Groups" column with a "Principals" column that renders both groups and users as badges, following the Teams view pattern:
- Groups: dark badge with `Users` (multi-person) icon
- Users: light badge with `User` (single-person) icon
- Truncated to 3 items with "+N more" badge if needed

### Badge-with-X Input for Both Groups and Users

The role form dialog replaces the comma-separated text input for groups with a badge-with-X component. The same component is used for both groups and users, with a text input to add new entries and X buttons on badges to remove them.

### Direct User Assignment is Admin-Only

Assigning individual users to roles is purely an admin action through the role form dialog. It does not interact with the existing "request access to role" workflow.

### Audit

The existing `updated_at` timestamp on the role is sufficient for now.

## Testing Decisions

### Testing Philosophy

Tests verify external behavior through public interfaces. Minimum viable coverage for this feature:

### Backend (pytest)

- **Authorization Manager**: `get_user_effective_permissions()` returns correct permissions for a user matched by email only, by group only, and by both. This is the critical path.
- **Frontend**: `checkUserHasRole()` returns true when user email matches `assigned_users`.

Prior art: `test_data_products_manager.py` for manager unit tests, `test_data_product_routes.py` for integration route tests.

## Out of Scope

- **User autocomplete from Databricks SCIM API**: Phase 2 enhancement. The data model supports it; only the UI input changes.
- **`is_user_admin` refactoring**: The standalone `is_user_admin()` utility function currently only checks groups and doesn't have access to `settings_manager`. Full admin checks already go through `PermissionChecker`, which will have the email-aware path.
- **Notification on role assignment**: No email/notification is sent when a user is directly assigned.
- **Bulk user import**: No CSV upload or SCIM sync for assigned users.
- **Role request flow changes**: The existing "request access to role" workflow doesn't change.
- **Separate audit log**: No per-assignment audit trail beyond the role's `updated_at`.

## Further Notes

- **Backward compatibility**: Fully backward compatible. The new column defaults to `'[]'`, all existing roles continue to work unchanged.
- **Performance**: `list_app_roles()` is already called on every permission check. Adding one more JSON field to deserialize is negligible for typical role counts (<20 roles).
- **Groups input UX upgrade**: While the primary feature is user assignment, upgrading the groups input from comma-separated text to badge-with-X is a small but valuable UX improvement that comes naturally with building the shared input component.
