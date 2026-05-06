# PRD: Entra ID / Microsoft Graph Integration & Unified Principal Picker

## Problem Statement

Across the app, users have to type principals (user emails, Databricks group names, service-principal names) into roughly fourteen different UIs that each implement the field differently: some are plain `Input` boxes, some are comma-separated strings, some are hard-coded `Select` lists, and several wizard placeholders are not even wired to a submit handler. There is no shared component, no validation, no display-name resolution, and no defense against typos. Operators with an Entra ID (Azure AD) tenant cannot pick principals from a directory; consumers of the app are left guessing whether `data-eng` or `data_engineering` is the correct group name; and the comment-audience and workflow-designer fields silently disagree on what a "principal" even is.

At the same time, the existing UC HTTP Connection plumbing — already used by the workflow webhook step — gives us a clean, secret-free way to talk to Microsoft Graph: Unity Catalog holds the OAuth client credentials and refreshes the bearer token on its own. The pieces are in place; what is missing is a single picker component, a small Graph search backend, and the migration of every existing principal-entry call site onto the new control.

## Solution

Add an **optional** Entra ID integration configured in Settings via a Unity Catalog HTTP Connection (the same UC `connections` listed for workflow webhooks). When configured, a new shared **PrincipalPicker** component performs Microsoft Graph lookups (Users + Groups) with both inline type-ahead and a popup search dialog, and emits the existing string identifiers expected by the backend (email for users, display name for groups). When not configured, the same component falls back to a Gmail-style badge input where typed values become removable badges and clicking a badge reverts it to editable text.

The picker replaces every principal-entry field across the app — assign-owner, role `assigned_groups`/`assigned_users`, entitlements persona groups, comment audience, review reviewer email, MDM reviewer, tag ACL `group_id`, team members (when type=group), workflow recipients/approvers (as a "custom principals" toggle next to the existing role selector), data-contract wizard placeholders, and the data-product/contract `team-member` dialogs.

No backend storage migration: the picker continues to read and write `string` and `List[str]` exactly as today. Type information (user vs group) is recovered at display time via Graph lookup and surfaced as a leading icon and a two-line row that always shows both the friendly `displayName` and the underlying email/UPN (for users) or group GUID (for groups) so two homonyms remain distinguishable.

## User Stories

### Settings configuration

1. As an **Admin**, I want to pick a UC HTTP Connection from a dropdown in a new "Entra ID" tab under Settings → Integrations, so that I can wire the app to Microsoft Graph without entering a client secret in our database.
2. As an **Admin**, I want a "Test connection" button that performs a real `/v1.0/users?$top=1` probe and tells me succinctly whether it worked, so that I can validate the UC connection before exposing the picker to users.
3. As an **Admin**, I want to clear the configured connection at any time, so that the app reverts cleanly to manual-entry mode.
4. As an **Admin**, I want the Settings page to explain exactly which UC HTTP Connection options to set (token URL, scope `https://graph.microsoft.com/.default`, base URL `https://graph.microsoft.com`, client-credentials grant), so that I can configure the connection in Unity Catalog without guessing.

### Configured-mode picking

5. As an **App user**, I want a principal field to start searching after I type 2 characters, with results debounced so that I do not hammer Graph on every keystroke.
6. As an **App user**, I want each search result row to show the display name on top and the email/UPN (for users) or GUID (for groups) underneath, so that I can disambiguate two people or two groups with the same friendly name.
7. As an **App user**, I want a leading icon on each result indicating whether it is a user or a group, so that I can scan the list visually.
8. As an **App user**, I want a small icon button next to the input that opens a wider popup dialog with a search box, type-filter chips (Users / Groups), and a scrollable result list, so that I can browse comfortably when picking many principals.
9. As an **App user**, I want my picked principals to appear as non-editable badges with the type icon and the display name, so that the form stays readable.
10. As an **App user**, I want hovering a badge to show a tooltip with the underlying email/UPN/GUID, so that I can confirm exactly which principal I picked even when the display name is ambiguous.
11. As an **App user**, I want to remove a badge with an X icon, so that I can correct mistakes quickly.
12. As an **App user**, I want multi-select fields to accept many picks (one badge per pick) and single-select fields to replace the previous pick, so that the picker matches the field's data shape.

### Unconfigured-mode picking

13. As an **App user with no Entra integration**, I want to type a principal and press Enter/Tab/comma to convert it into a badge, so that the field still has a structured look.
14. As an **App user with no Entra integration**, I want to click an existing badge to revert it to editable text, so that I can fix typos without deleting and re-typing.
15. As an **App user with no Entra integration**, I want a non-blocking format hint (e.g. email regex for fields that accept users), so that I notice obvious typos without being prevented from saving.
16. As an **App user with no Entra integration**, I want to remove a badge with an X icon, identical to the configured-mode behaviour.

### Pre-existing data

17. As an **App user**, I want existing principals stored before Entra was configured to render as plain badges (no error icon, no forced re-pick), so that turning on the integration does not break my historical records.
18. As an **App user**, I want to remove and re-pick those legacy badges if I want them to be Graph-resolved, so that I can opt-in to validation per-record.

### Per-feature migration (call-site coverage)

19. As a **Data steward**, I want to pick a business owner via the Entra picker on the Assign Owner dialog, so that I can grant ownership without copy-pasting an email.
20. As an **Admin**, I want to pick groups (and users, per the existing individual-user-role-assignment PRD) for App Roles via the Entra picker, so that the Roles form is consistent with the rest of the app.
21. As an **Admin**, I want to pick groups for personas in Entitlements via the Entra picker, replacing the hard-coded demo list, so that real groups are addressable.
22. As a **Data product author**, I want to pick a reviewer for a Data Asset Review via the Entra picker, so that I do not mistype the reviewer email.
23. As an **MDM author**, I want the same picker for the MDM review reviewer field, so that the experience is consistent.
24. As an **Admin**, I want to pick a Databricks group when granting tag-namespace permissions via the Entra picker, so that I cannot grant access to a non-existent group.
25. As a **Team admin**, I want the team-members dialog to use the Entra picker for both `user` and `group` member types, so that team membership is verifiable.
26. As a **Workflow author**, I want a "Custom principals" toggle on the workflow designer's notification recipients and approval approvers, that reveals the Entra picker so that I can target specific users/groups (not only roles), matching what the backend already accepts.
27. As a **Comment author**, I want the comment audience field to use the Entra picker (in addition to the existing team/role checkbox lists), so that I can mention an arbitrary user or group.
28. As a **Data contract author**, I want the data-contract wizard's owner / stakeholders / groups / primary-support-email placeholder fields to be wired to a real Entra picker, so that those fields actually persist.
29. As a **Data product / contract author**, I want the team-member dialogs in both the products and contracts views to use the Entra picker for the email/username field, so that the team list is trustworthy.

### Backwards compatibility

30. As an **API consumer**, I want existing JSON payloads to keep working unchanged (still `List[str]` of emails or group names), so that integrations do not break.
31. As an **Operator**, I want the picker to gracefully degrade to manual mode if Entra is configured but Graph is unreachable (network error or revoked credentials), so that I can keep working.

## Implementation Decisions

### Auth: UC HTTP Connection only

The app calls `ws.serving_endpoints.http_request(conn=connection_name, method="GET", path="/v1.0/users?$filter=...&$select=id,displayName,userPrincipalName,mail&$top=20", headers=None, json=None)`. Unity Catalog handles OAuth2 client-credentials token acquisition, caching, and refresh. **The app keeps no token cache and stores no client secret** — this is the same pattern proven by `WebhookStepHandler._execute_via_uc_connection` in `src/backend/src/common/workflow_executor.py`. The TypeScript sample in the original request (with `getAccessToken` and `tokenExpiry`) is illustrative of the Graph API shape, not a model to port.

### New backend module: `EntraIdManager`

Located at `src/backend/src/controller/entra_id_manager.py`. Responsibilities:

- `is_configured() -> bool`: reads `ENTRA_UC_HTTP_CONNECTION_NAME` from `SettingsManager`.
- `search_users(prefix: str, top: int = 20) -> list[Principal]`: Graph `GET /v1.0/users?$filter=startswith(displayName,'{p}') or startswith(userPrincipalName,'{p}') or startswith(mail,'{p}')&$select=id,displayName,userPrincipalName,mail&$top={top}` with `ConsistencyLevel: eventual` header for `$filter`.
- `search_groups(prefix: str, top: int = 20) -> list[Principal]`: Graph `GET /v1.0/groups?$filter=startswith(displayName,'{p}') or startswith(mailNickname,'{p}')&$select=id,displayName,mailNickname&$top={top}`.
- `get_user(upn_or_email: str) -> Principal | None` and `get_group(id_or_displayname: str) -> Principal | None`.
- `test() -> tuple[bool, str | None]`: a `/v1.0/users?$top=1` probe returning `(healthy, error_message)`.
- All public methods normalise to a single `Principal` Pydantic model:
  - `type: Literal['user', 'group']`
  - `id: str` — `userPrincipalName` for users (fallback `mail`), `id` (GUID) for groups
  - `display_name: str`
  - `sub_label: str` — email/UPN for users, GUID for groups (used by the UI for the second line)

Input prefixes are escaped against OData injection (single-quote doubling, no other special characters allowed in the prefix). Errors from Graph are wrapped with the response status and a short message.

### New backend routes

In a new file `src/backend/src/routes/entra_routes.py`, mounted at `/api/entra`:

- `GET /api/entra/status` → `{ configured: bool, connection_name: str | null }` (settings READ_ONLY).
- `GET /api/entra/search?q=&types=users,groups&limit=20` → `Principal[]` (any authenticated user; access control on the picker is governed by the surrounding form, not the search itself).
- `POST /api/entra/test` → `{ healthy: bool, error?: string }` (settings READ_WRITE).

### Settings storage

Single new key `ENTRA_UC_HTTP_CONNECTION_NAME` written to the existing `app_settings` key/value table. No Alembic migration. Loaded in `SettingsManager._load_persisted_settings()`, persisted in `SettingsManager.update_settings()`, and exposed in `get_settings()` so the UI can render it.

### Shared HTTP-connection helper

Extract the HTTP-connection list logic currently inline at `src/backend/src/routes/workflows_routes.py` lines 259–289 into a shared helper (e.g. `src/backend/src/common/uc_connections.py::list_http_connections(ws)`) and expose it at `GET /api/settings/uc-http-connections`. The workflow route delegates to the same helper. Both routes use the OBO workspace client via `get_obo_workspace_client(request)`.

### Backend cache

A small in-memory TTL cache (5 minutes) keyed on `(query, type)` lives inside `EntraIdManager` to soften Graph throttling under bursts. Not persisted; not user-scoped (queries are not sensitive). Cache is cleared when the connection name changes.

### Shared frontend component: `PrincipalPicker`

Location: `src/frontend/src/components/common/principal-picker.tsx`. TypeScript surface:

```
type Principal = {
  type: 'user' | 'group' | 'unknown'
  id: string
  displayName?: string
  subLabel?: string
}

interface PrincipalPickerProps {
  value: string[] | string                     // current ids (emails / group names)
  onChange: (next: string[] | string) => void
  multiple?: boolean                            // default false
  accepts: ('user' | 'group')[]                 // restricts search and manual-entry hints
  placeholder?: string
  disabled?: boolean
  fieldName?: string                            // for accessibility / form integration
}
```

- On mount the component reads `/api/entra/status` from a small Zustand `entra-store` (request shared across all instances on the page).
- **Configured mode**: typed input triggers a 250ms-debounced `/api/entra/search` after 2 chars; results render in a Combobox dropdown using `cmdk` (already a dep via shadcn). Each row is two lines: bold `displayName` on top, muted `subLabel` underneath, with a leading type icon (matches the existing Teams-view pattern: dark badge + Users icon for groups, light badge + User icon for users). When two displayed rows share `displayName`, the differing `subLabel` is highlighted.
- A small icon button ( `Search` icon) next to the input opens a `Dialog` containing a wider search input, type-filter chips honouring `accepts`, and a scrollable list using the same row layout. Picks from the dialog also become badges and the dialog stays open for `multiple` fields.
- Selected items render as non-editable badges with the type icon + `displayName`. Tooltip + `title` attribute on the badge expose `subLabel` so hover reveals the underlying id.
- **Unconfigured mode**: typed value becomes a plain badge on Enter/Tab/comma. Click on badge → it reverts to editable text in place; pressing Enter/Tab/comma re-confirms; Escape cancels and restores the previous value. Email-format hint (non-blocking) when `accepts` includes `user`. X icon to remove.
- Storage compatibility: `value` is always `string` (single) or `string[]` (multi). When the picker resolves a Graph principal, it stores `principal.id` (email/UPN for users, display name for groups — see below). When the user types manually, it stores the literal text.

### Group identifier choice

For groups the component stores `displayName` (not the GUID) in `value`, because the existing backend models (`assigned_groups`, persona `groups`, tag `group_id`, comment audience, etc.) all expect human-readable group names that match what Databricks SCIM exposes. The GUID is shown as `subLabel` for disambiguation but not persisted. A future PRD can introduce a parallel optional GUID column if Databricks group sync ever introduces ambiguity.

### Settings UI

New nav item under **Integrations** in `src/frontend/src/components/settings/settings-layout.tsx` ("Entra ID"). New view file `src/frontend/src/views/settings-entra.tsx` wrapping a new component `src/frontend/src/components/settings/entra-settings.tsx`. Component contents:

- A `Select` populated from `GET /api/settings/uc-http-connections` (filtered to HTTP type) showing each connection's name and connection_type.
- A "Test connection" button that calls `POST /api/entra/test` and shows success/failure via `useToast` (mirrors the connectors-settings test pattern).
- A "Clear" button that nulls the setting (hits `PUT /api/settings`).
- A help block describing the required UC HTTP Connection setup.

### Migration of the 14 call sites

| Group | File | Field | Picker config |
|------|------|-------|---------------|
| 1. Single user | `src/frontend/src/components/common/assign-owner-dialog.tsx` | `userEmail` | `multiple=false, accepts=['user']` |
| 1. Single user | `src/frontend/src/components/data-asset-reviews/create-review-request-dialog.tsx` | `reviewer_email` | `multiple=false, accepts=['user']` |
| 1. Single user | `src/frontend/src/components/mdm/create-review-dialog.tsx` | `reviewer_email` | `multiple=false, accepts=['user']` |
| 1. Single user | `src/frontend/src/components/data-products/team-member-form-dialog.tsx` | `username` | `multiple=false, accepts=['user']` |
| 1. Single user | `src/frontend/src/components/data-contracts/team-member-form-dialog.tsx` | `email`/`username` | `multiple=false, accepts=['user']` |
| 2. Multi user/group | `src/frontend/src/components/settings/role-form-dialog.tsx` | `assigned_groups` | `multiple=true, accepts=['group']` |
| 2. Multi user/group | `src/frontend/src/components/settings/role-form-dialog.tsx` | `assigned_users` (per individual-user-role-assignment PRD) | `multiple=true, accepts=['user']` |
| 2. Multi user/group | `src/frontend/src/views/entitlements.tsx` | persona `groups` | `multiple=true, accepts=['group']` |
| 2. Multi user/group | `src/frontend/src/components/comments/comment-sidebar.tsx` | `audience` (in addition to existing team/role checkboxes) | `multiple=true, accepts=['user','group']` |
| 3. Group only | `src/frontend/src/components/settings/tags-settings.tsx` | `permissionForm.group_id` | `multiple=false, accepts=['group']` |
| 3. Group only | `src/frontend/src/components/teams/team-form-dialog.tsx` | `member_identifier` when `member_type==='group'` | `multiple=false, accepts=['group']` |
| 3. User only | `src/frontend/src/components/teams/team-form-dialog.tsx` | `member_identifier` when `member_type==='user'` | `multiple=false, accepts=['user']` |
| 4. Workflow designer | `src/frontend/src/components/workflows/workflow-designer.tsx` | notification `recipients` (custom toggle) | `multiple=true, accepts=['user','group']` |
| 4. Workflow designer | `src/frontend/src/components/workflows/workflow-designer.tsx` | approval `approvers` (custom toggle) | `multiple=true, accepts=['user','group']` |
| 5. Wizard placeholders | `src/frontend/src/components/data-contracts/data-contract-wizard-dialog.tsx` | `dc-owner`, stakeholders, groups, primary support email (currently unwired) | per-field accepts |

For the workflow designer (#4), the existing role-based `Select` is preserved — a "Custom principals…" toggle reveals the picker, and the resulting strings are sent as additional `recipients`/`approvers` entries (the backend already accepts email/group literals, the UI just did not surface them).

### i18n

A new `entra` namespace added to all 8 locale files under `src/frontend/src/i18n/locales/{en,de,es,fr,it,ja,nl}/entra.json` (and registered in the i18n config), mirroring the structure of `semantic-models.json`. Picker strings live under `common.principalPicker.*` so they are reusable.

### Backwards compatibility

- All existing API request/response shapes unchanged (still strings).
- Existing rows in the database render as plain badges with no leading icon and no error decoration; they are distinguishable from Graph-resolved badges by the absence of the type icon.
- If the configured Graph connection becomes unreachable, the picker logs a single console warning and falls back to manual-entry mode for the rest of the session.

## Testing Decisions

### Testing philosophy

Tests verify external behaviour through public interfaces. We do not test the picker's internal cmdk state machine; we test what the user sees and what the backend receives.

### Backend (pytest)

- `EntraIdManager`: unit tests against a mocked `serving_endpoints.http_request` covering `search_users`, `search_groups`, OData-injection escaping, the eventual-consistency header, and `Principal` normalisation for both users and groups (including missing `mail` → fallback to `userPrincipalName`).
- `EntraIdManager.test()` returns `(False, error_message)` on a non-200 Graph response and `(True, None)` on success.
- Routes (`/api/entra/status`, `/api/entra/search`, `/api/entra/test`) integration-tested via FastAPI test client with a mocked manager: auth required, parameter validation, and shape of the response.
- `SettingsManager`: persists and reloads `ENTRA_UC_HTTP_CONNECTION_NAME` correctly; `get_settings()` exposes it.
- Shared `list_http_connections` helper: filters non-HTTP connections out.

Prior art: `src/backend/src/tests/integration/test_knowledge_routes.py`, `src/backend/src/tests/unit/` for manager-level mocks.

### Frontend (vitest + React Testing Library)

- `PrincipalPicker` configured-mode: 2-char trigger, debounced search, two-line rows render `displayName` and `subLabel`, picking adds a badge, badge tooltip exposes `subLabel`, X removes.
- `PrincipalPicker` unconfigured-mode: Enter/Tab/comma converts text → badge, click on badge reverts to text, Escape cancels.
- `PrincipalPicker` accepts filter: requesting `accepts=['group']` only sends `types=groups` to the search endpoint.
- `entra-settings.tsx`: Test button shows success vs destructive toast based on response.

Prior art: `src/frontend/src/components/settings/role-form-dialog.test.tsx`, `src/frontend/src/components/semantic/concept-neighborhood-graph.test.tsx`.

### Manual / opt-in

A short manual smoke test against a real UC HTTP Connection wired to a tenant — documented in the PR description, not automated.

## Out of Scope

- **Service principals**: deferred. Graph supports `/servicePrincipals`; adding it later is a single new method and a new value in the `accepts` union.
- **Storage migration to structured Principal records**: explicitly rejected — keep `string` / `List[str]`. Type info is recovered at display time.
- **Bulk re-validation of pre-existing values**: no migration script. Legacy values keep working; users opt-in by re-picking.
- **OBO / delegated Graph queries**: connection always uses app-level client credentials. No per-user permission checks against the directory.
- **User profile photos, manager hierarchies, `$expand=manager`, group membership traversal**: not needed for the picker.
- **Server-side display-name caching beyond the 5-minute query cache**: defer until rate-limit pressure is observed.
- **Replacing the existing role/team `Select`s in the workflow designer**: kept as-is; the picker is additive via a "Custom principals" toggle.
- **CSV import / bulk add**: not in v1.

## Further Notes

- **Why UC handles OAuth, not the app**: removes a class of secret-management bugs (no client secret in `app_settings`, no token cache to invalidate, no refresh logic), and keeps the integration story consistent with the workflow webhook step which already proves the pattern.
- **Disambiguation rule recap**: every search result shows `displayName` + `subLabel`; every selected badge exposes `subLabel` via tooltip + `title` attr. This is a hard requirement — homonyms in directories of any meaningful size are common (Microsoft Graph routinely returns multiple "John Smith" entries) and silently picking the wrong one is the most expensive failure mode of any directory picker.
- **Performance**: 250ms debounce + 2-char minimum + 5-minute backend TTL cache should keep us well under Graph's per-app throttling thresholds for normal usage.
- **Accessibility**: badges use `aria-label` containing `displayName` + `subLabel`; the popup dialog is focus-trapped; the type filter chips are reachable via Tab.
- **Forward path**: a v2 PRD can introduce structured Principal columns (with type discriminator) on the highest-traffic tables (e.g. `app_roles.assigned_users`) once we have data on how often homonym collisions cause real bugs.
