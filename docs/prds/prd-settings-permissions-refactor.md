# PRD: Settings Permissions Refactor + Grouped Permissions UI

## Problem Statement

The Settings area of the application currently has a single, coarse permission named `settings` with only two access levels: `None` and `Admin`. This forces an all-or-nothing model where any user who needs to manage a single Settings sub-page (say, Business Roles or Tags) must be granted full Admin over every other Settings sub-page — including sensitive ones like Git integration, MCP tokens, App Roles, and Connectors.

In practice, this means:

- **Administrators** cannot delegate operational ownership. A Data Steward who should curate the Business Glossary and Business Roles is either locked out of `/settings` entirely or handed the keys to every infrastructure setting.
- **Operators** of specific surfaces (Platform Engineers, Security Officers, Glossary Owners) have no role between "no Settings access" and "full system Admin".
- **The role configuration UI** lists every feature permission in one flat scroll-list. With 30+ features, it is hard for an Admin to find a particular permission, hard to reason about which permissions belong together, and hard to onboard a new persona.

Additionally, every Settings sub-page (`/settings/general`, `/settings/git`, `/settings/jobs`, etc.) is currently gated solely by the single `settings` permission via `SettingsPageWrapper`. There is no mechanism to express "this role can manage X but not Y inside Settings".

## Solution

Replace the single coarse `settings` permission with a layered model:

1. The `settings` permission becomes a **layout gate** with the full four-level scale (`None` / `Read-only` / `Read/Write` / `Admin`). Holding at least `Read-only` allows a user to open `/settings` and see the Settings sidebar shell.
2. Every Settings sub-page gets its own dedicated permission with the full four-level scale (e.g., `settings-business-roles`, `settings-git`, `settings-jobs`, `settings-mcp`, ...). The Settings sidebar dynamically filters items based on which sub-permissions the user holds. Each sub-page enforces its own permission on both its UI actions and its backend API endpoints.
3. The Role configuration dialog groups every permission in the system by the same logical groups used in the main sidebar — **Discover**, **Build**, **Govern**, **Deploy**, plus a new **Settings** group and an **Other** bucket for cross-cutting permissions. Each group renders under a styled section header so Admins can scan and configure permissions feature-area by feature-area.

The result is a permission model that supports fine-grained delegated administration of Settings, plus a role-configuration UI that scales with the number of features.

## User Stories

### Administrators configuring roles

1. As an **Admin**, I want to grant a role permission to manage Business Roles without giving that role any access to Git integration or App Roles, so that I can safely delegate glossary curation to a Data Steward.
2. As an **Admin**, I want to see all feature permissions grouped under headings that match the main app sidebar (Discover, Build, Govern, Deploy, Settings, Other), so that I can find the permission I'm looking for without scanning a flat list.
3. As an **Admin**, I want a dedicated "Settings" group inside the role permissions UI that lists every Settings sub-page permission together, so that I can build delegated-administration personas in one place.
4. As an **Admin**, I want each Settings sub-page permission to support the same four levels (None, Read-only, Read/Write, Admin) as other features, so that I can express "view only", "edit but don't delete", and "full control including destructive actions" consistently.
5. As an **Admin**, I want my Admin role to keep working after the upgrade without my having to re-grant any settings sub-permissions, so that the change is invisible from my perspective.
6. As an **Admin**, I want existing non-Admin roles that today have `settings: None` to remain at `None` for every new sub-permission, so that no one accidentally gains new access during the upgrade.
7. As an **Admin**, I want the Role dialog to remember which group sections I've collapsed, so that I can focus on the area I'm editing without losing my place.
8. As an **Admin**, I want the Settings sub-permissions inside the Settings group to be ordered the same way as the Settings sidebar (Reference Data → Configuration → Integrations → Operations → Access Control), so that the matrix mirrors the user-facing navigation.

### Delegated personas operating Settings

9. As a **Data Steward**, I want to manage Business Roles, Delivery Methods, Asset Types, Teams, Projects, Tags, and Certification Levels from `/settings/*` without holding Admin, so that I can run governance reference data without needing infrastructure access.
10. As a **Platform Engineer**, I want to manage Git integration, Jobs, Connectors, and Workflows from `/settings/*` without holding Admin, so that I can configure operational plumbing without owning glossary or role data.
11. As a **Security Officer**, I want exclusive Admin access to App Roles, MCP tokens, and the Audit Trail without holding settings rights elsewhere, so that least-privilege separation of duties is enforced.
12. As a **Search Configuration Owner**, I want to manage `/settings/search` and `/settings/semantic-models` (RDF Sources) without any other Settings access, so that I can tune search behavior without touching governance data.
13. As a **non-Admin user with limited Settings access**, I want to see only the Settings sidebar items I am permitted to use, so that I am not confused by clickable pages that immediately deny me.
14. As any **user without `settings >= Read-only`**, I want `/settings` to redirect or show a clean access-denied state, so that the existence of Settings does not create a dead-end in the navigation.
15. As a user **without permission for a specific sub-page**, I want a clear access-denied message if I land on it via a direct URL or bookmark, with a link back home and an indication to request a role.

### Backend / API consumers

16. As an **API caller**, I want backend Settings endpoints to enforce the same `settings-<name>` permissions that the UI enforces, so that a user cannot bypass UI gating by calling the API directly.
17. As an **API caller**, I want endpoints that back Reference-Data sub-pages (Domains, Teams, Projects, etc.) to still be callable by users who hold the underlying feature permission for non-Settings consumption (e.g., a domain picker dropdown), so that read access from outside Settings is not regressed.
18. As an **integration developer**, I want `/api/settings/features` to include a `group` field for every feature, so that any external tool that introspects the permission model can render it the same way as the in-app Role dialog.

### Existing flows that must continue to work

19. As a current **Admin user**, I want to log in after the upgrade and continue to access every Settings sub-page with full edit rights, so that the upgrade is non-breaking.
20. As an **end user** of features that have a Settings counterpart (e.g., browsing a Domain picker), I want my access to the underlying feature to be unchanged — the new `settings-*` permissions only affect the Settings management UI, not feature consumption.
21. As an **Admin who has customized the built-in roles**, I want the post-upgrade Admin role to receive `Admin` on every new `settings-*` permission automatically (idempotent on startup), so that I do not have to edit it.
22. As an **Admin**, I want existing non-Admin roles to remain unchanged on upgrade (every new `settings-*` permission starts at `None` for them), so that I retain explicit control over who I delegate to.

### Visibility and discoverability

23. As any **user**, I want the main app sidebar to show or hide the link to `/settings` based on my `settings` permission, so that the navigation reflects what I can actually do.
24. As a **user requesting a role**, I want to see roles that grant the specific Settings sub-page access I need (e.g., "Tag Curator"), so that I can request the right level of delegation.
25. As an **Admin browsing existing roles**, I want the per-role permissions display in the roles list to also be grouped by the new groups, so that role definitions read consistently with the editor.

## Implementation Decisions

### Permission model

- Introduce a `group` attribute on every feature in the central feature catalog. Valid values: `Discover`, `Build`, `Govern`, `Deploy`, `Settings`, `Other`.
- Promote the `settings` permission from a two-level (`None`/`Admin`) feature to the standard four-level scale (`None`/`Read-only`/`Read/Write`/`Admin`). It functions purely as a layout gate.
- Add one dedicated `settings-<name>` permission per Settings sub-page, each at the four-level scale. The clean-cut approach is used: no Settings sub-page reuses an existing top-level feature ID. The new IDs are:
  - Reference Data: `settings-data-domains`, `settings-business-roles`, `settings-delivery-methods`, `settings-asset-types`, `settings-teams`, `settings-projects`, `settings-certification-levels`
  - Configuration: `settings-general`, `settings-ui`, `settings-tags`, `settings-connectors`
  - Integrations: `settings-git`, `settings-mcp`, `settings-semantic-models`, `settings-search`
  - Operations: `settings-jobs`, `settings-delivery`, `settings-workflows`
  - Access Control: `settings-roles`, `settings-audit`
- Existing top-level feature IDs that share a name with a Settings sub-page (`data-domains`, `teams`, `projects`, `business-roles`, `delivery-methods`, `tags`, `semantic-models`, `jobs`, `audit`) remain in place and govern *consumption* of the underlying feature elsewhere in the app. They are assigned to the `Other` group.

### Backend modules to modify

- **Feature catalog module** (`common/features`): adds the `group` field and the new permission IDs; updates the `settings` allowed-levels list.
- **Settings manager**: extends the response of the features-with-access-levels endpoint to include the `group` field.
- **Settings routes**: routes that previously called `PermissionChecker('settings', ...)` switch to the appropriate `settings-<name>` ID. This covers settings, workflows, certification levels, MCP tokens, connections, and approvals routes.
- **Reference-Data routes** (domains, teams, projects, business roles, delivery methods, asset types, tags, jobs, audit, semantic models): write endpoints get an additional composite dependency that requires the corresponding `settings-<name>` permission alongside the existing underlying permission, so the Settings-page gate is also enforced at the API layer. Read endpoints used outside Settings keep only the underlying check.
- **Role seeder / startup task**: an idempotent step that ensures the built-in Admin role is granted `Admin` on every new `settings-*` permission ID. Other roles are left untouched.

### Frontend modules to modify

- **Feature config type** (`types/settings`): extends `FeatureConfig` with an optional `group` field.
- **`SettingsPageWrapper`**: gains a required `permissionId` prop and gates rendering on both the layout permission (`settings >= Read-only`) and the page permission (`permissionId >= Read-only`).
- **Each settings view file** (`views/settings-*.tsx`): passes its dedicated `settings-<name>` permissionId to the wrapper.
- **`SettingsLayout` sidebar component**: each nav item now carries a `permissionId`; items are filtered by `hasPermission(permissionId, Read-only)`; empty groups are hidden; the whole layout redirects if `settings < Read-only`.
- **Route table** (`app.tsx`): the Reference-Data sub-pages (data-domains, teams, projects, business-roles, delivery-methods, asset-types, audit-trail) that render standalone views under `/settings/*` are wrapped in `SettingsPageWrapper` at the route element layer.
- **Per-sub-page setting components**: their `hasPermission('settings', ...)` calls are switched to the dedicated `settings-<name>` IDs at the appropriate level (Read/Write for edits, Admin for destructive actions).
- **Role configuration dialog**: replaces the flat feature-permissions list with a grouped rendering. Groups are ordered Discover, Build, Govern, Deploy, Settings, Other. Items in the Settings group follow the order of the Settings sidebar; items in other groups are sorted alphabetically by display name.
- **i18n locale files**: add display name and short description keys for each new `settings-*` permission, plus group header labels for the Role dialog, across all supported locales (de, en, es, fr, it, ja, nl).

### API contract changes

- `GET /api/settings/features` returns `group` for every feature, in addition to `name` and `allowed_levels`.
- No new endpoints. No changes to role storage format — role JSON simply contains entries for the new permission IDs once a role is saved.
- All existing endpoints continue to accept the same payloads; only the `PermissionChecker` IDs change internally.

### Migration / rollout

- No database migration required; permissions are config-driven and stored as JSON on each role.
- On application startup, the role seeder ensures the built-in **Admin** role is granted `Admin` on every new `settings-*` permission ID. Idempotent.
- All other existing roles inherit `None` for every new `settings-*` permission on their next read. Admins must explicitly grant new delegated access to non-Admin roles.

### Interaction details

- A user with `settings: Read-only` and `settings-git: None` can open `/settings`, see the sidebar, but the Git item is hidden and direct navigation to `/settings/git` shows access denied.
- A user with `settings: None` cannot open `/settings` at all, regardless of what `settings-*` permissions they hold (defense in depth).
- The Settings group header in the Role dialog is rendered with the same uppercase/tracking style as the Settings sidebar group headings, for visual continuity.

## Testing Decisions

### What makes a good test

Tests should exercise externally observable behavior — API responses, rendered UI based on a given permission set, gate decisions — without coupling to internal implementation details like specific function names or component internals. Permission-related tests should drive observable outcomes: HTTP status codes for backend, presence/absence of UI elements and access-denied states for frontend.

### Modules to be tested

- **Backend feature catalog**: a unit test asserts that `get_features_with_access_levels()` returns a `group` field for every feature, that `settings` has all four access levels, and that each new `settings-*` permission ID is present with the four-level scale.
- **Backend route gating**: an integration test per representative settings sub-page (general, git, jobs, roles, business-roles) verifies that calls succeed/fail correctly under each combination of `settings` and `settings-<name>` permissions. Existing tests for routes that switched permission IDs are updated.
- **Backend role seeder**: a test asserts that after running the seeder on a fresh DB and on a DB with a pre-existing Admin role, the Admin role ends up with `Admin` on every new `settings-*` permission ID, and that non-Admin roles are not mutated.
- **Frontend permissions store**: a unit test verifies that the `hasPermission` helper correctly distinguishes `settings` from `settings-<name>` and respects each independently, including the four-level ordering.
- **Frontend SettingsLayout sidebar filtering**: a component test renders the layout under different permission sets and asserts which sidebar items are visible, including hiding empty groups.
- **Frontend Role dialog grouping**: a component test renders the dialog with a mocked features response and asserts that features are grouped under the correct headings in the correct order (Discover, Build, Govern, Deploy, Settings, Other) and that Settings items follow the sidebar order.

### Prior art in the codebase

- Backend permission integration tests follow the patterns already established in `tests/unit/test_settings_manager.py` for permission-related assertions.
- Frontend permission gating tests follow the pattern in `stores/permissions-store.test.ts`.
- Component-level snapshot or rendering tests follow patterns used for other Shadcn-based dialogs in the project.

## Out of Scope

- Splitting any non-Settings feature into finer-grained sub-permissions. This PRD only touches Settings; other features keep their existing single-level permissions.
- Per-row or per-domain access (data-domain-scoped permissions, ABAC, OpenFGA evaluation). The model remains role-based with feature-level granularity.
- A UI for end users to discover what permissions they hold or what they would need to perform an action — only the existing Role configuration UI is in scope.
- Changing the storage format of roles or the `/api/user/permissions` response envelope. Both continue to be feature-id → level dictionaries.
- Adding new high-level feature areas to the sidebar or renaming existing groups (Discover/Build/Govern/Deploy).
- Permission management for the About page, Home page, and other public/static pages.

## Further Notes

- The clean-cut decision (every Settings sub-page gets a dedicated permission ID rather than reusing the underlying feature ID) was made because it cleanly separates "managing X via the Settings UI" from "consuming X elsewhere in the app". This avoids ambiguity around what permission a generic `data-domains: Read/Write` grant is intended to authorize.
- The composite check pattern on Reference-Data write routes (require both the underlying permission and the `settings-<name>` permission) means a user can still read domain data via API for the domain picker even if they have no Settings access; but mutating domains via API still requires the Settings delegation. This matches the principle that the Settings UI gate also closes at the API layer.
- The `Other` group serves as a holding pen for cross-cutting permissions that don't belong to a sidebar area (notifications, comments, self-service, ontology, entity relationships, etc.) plus the legacy top-level IDs that overlap with Settings sub-pages. Future PRDs may decide to relocate some of these as the application grows.
- The Role dialog grouping is the visible payoff of this PRD for Admins. The new permission IDs will likely number ~50+ once Settings sub-permissions are added; without grouping, the dialog would become significantly harder to use.
