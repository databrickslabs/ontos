# Plan: Directory Lookup Integration & Unified Principal Picker

> Source PRD: [docs/prds/prd-entra-id-graph-integration.md](../docs/prds/prd-entra-id-graph-integration.md) — GitHub [#335](https://github.com/databrickslabs/ontos/issues/335)
> Tracking PR for PRD batch: [#336](https://github.com/databrickslabs/ontos/pull/336)

> Naming note: the PRD is written Entra-first; this plan uses the **generic Directory abstraction** (`DirectoryManager` + `/api/directory/*`) discussed during planning. The PRD will be amended in a small follow-up to document the abstraction. Behaviour for the v1 user is unchanged: Entra is the only concrete provider shipped.

## Architectural decisions

Durable decisions that apply across all phases:

- **Naming**: the backend layer that resolves principals against an external IdP is the **Directory** layer. Manager: `DirectoryManager`. Concrete provider plug-ins live behind a single `DirectoryProvider` interface. v1 ships one provider for Entra ID / Microsoft Graph; Okta / Ping / others are explicit future-phase work and must not require breaking changes to the manager or routes.
- **Auth**: every provider talks to its IdP exclusively via a Unity Catalog HTTP Connection using `ws.serving_endpoints.http_request(conn=name, method=..., path=..., headers=..., json=...)`. UC owns OAuth2 client-credentials acquisition, caching, refresh. The app stores no client secret and no token cache. (Pattern matches the workflow webhook step.)
- **Settings keys** (single source of truth, persisted in the existing `app_settings` key/value table — no Alembic migration):
  - `DIRECTORY_PROVIDER_TYPE` ∈ `{ entra }` (extensible enum; unknown values are treated as not-configured)
  - `DIRECTORY_UC_HTTP_CONNECTION_NAME` (string, the UC HTTP Connection name)
  - "Configured" ⇔ both are non-empty AND the provider type is recognised.
- **Routes** (REST, all under `/api`):
  - `GET /api/directory/status` → `{ configured: bool, provider_type: string | null, connection_name: string | null }`
  - `GET /api/directory/search?q=&types=users,groups&limit=20` → `Principal[]`
  - `POST /api/directory/test` → `{ healthy: bool, error?: string }` (settings-write permission)
  - `GET /api/settings/uc-http-connections` → `[{ name, connection_type, ... }]` (extracted from the existing workflows endpoint into a shared helper, both routes delegate to it)
- **`Principal` model** (Pydantic on backend, mirrored TS interface on frontend, used by every provider and every UI surface):
  - `type`: `'user' | 'group'` (service principal reserved for v2; UI may render `'unknown'` for legacy values that have no resolved type)
  - `id`: persisted identifier — email/UPN-equivalent for users, displayName for groups (NOT GUIDs)
  - `display_name`: friendly name shown on the badge / row
  - `sub_label`: secondary identifier shown on the second line of search rows and exposed via tooltip on selected badges (email/UPN for users, GUID for groups)
- **Storage compatibility**: every existing principal-bearing field on the backend keeps its current shape (`str` or `List[str]` of emails / group display-names). The picker emits and consumes only those strings. No DB migrations are introduced for any of the migrated call sites in v1.
- **Disambiguation rule**: every search result row in both the type-ahead dropdown and the popup dialog is two lines: bold `display_name` on top, muted `sub_label` underneath, with a leading type icon. Selected badges expose `sub_label` via tooltip + `title` attribute. This is required, not optional — homonyms in real directories are common and silently picking the wrong one is the most expensive failure mode.
- **Provider abstraction shape**: every concrete provider implements `search_users(prefix, top)`, `search_groups(prefix, top)`, `get_user(id)`, `get_group(id)`, `test()`. All methods accept normalised inputs and return normalised `Principal` instances; field mapping (Graph `userPrincipalName` vs Okta `profile.login` vs Ping `username`, etc.) lives entirely inside the provider.
- **Caching**: a per-instance in-memory TTL cache (5 min) keyed on `(provider_type, query, types)` lives inside `DirectoryManager`. Cleared whenever the provider type or connection name changes. Not persisted, not user-scoped.
- **Shared frontend component**: `PrincipalPicker` is a single component supporting both modes (configured / unconfigured) and both UI variants (inline type-ahead + popup dialog) selected at runtime by `directory.status`. No separate "configured-only" or "manual-only" component.
- **Graceful degradation**: if `directory.status` reports configured but a search call fails, the picker logs once and falls back to manual-entry mode for the rest of the session. Pre-existing values render as plain badges with no error decoration regardless of provider availability.
- **Migration scope**: every principal-entry field across the app moves to `PrincipalPicker` in v1. No call site keeps a bespoke control. Workflow designer and data-contract wizard are the only places where the picker co-exists with existing controls (additive toggle / first-time wiring of dead UI, respectively).

---

## Phase 1: Foundation + Settings + Picker tracer bullet (Assign Owner)

**User stories**: 1, 2, 3, 4 (settings configuration); 5, 6, 7, 8, 9, 10, 11, 12 (configured-mode picking); 13, 14, 15, 16 (unconfigured-mode picking); 17, 18 (pre-existing values); 19 (Assign Owner integration); 30, 31 (backwards compatibility & graceful degradation)

### What to build

A single end-to-end vertical slice that proves every layer of the directory feature works together. After Phase 1 the rest of the work is horizontal migration of existing fields onto the same picker, with no new architecture required.

The slice covers:

- A `DirectoryManager` that reads its provider type and connection name from settings, dispatches to the right `DirectoryProvider`, returns normalised `Principal` results, and exposes a `test()` probe.
- One concrete provider, `EntraIdProvider`, that calls Microsoft Graph through the configured UC HTTP Connection with safe OData escaping, the eventual-consistency header, and `$select` projections that keep responses small. The provider produces `Principal` records with `id` set to UPN/email for users and displayName for groups, and `sub_label` set to the secondary identifier.
- The four routes listed in the architectural decisions, with permission gates matching existing settings/search routes.
- A new "Directory" tab under Settings → Integrations that shows: a provider-type `Select` (only Entra ID enabled in v1, others visible-but-disabled to telegraph the abstraction), a UC HTTP Connection `Select` populated from `/api/settings/uc-http-connections`, a Test button with success/destructive toast feedback (mirrors the connectors-settings test pattern), a Clear button, and a provider-specific help block describing the required UC connection setup (token URL, scope, base URL, grant type).
- A `PrincipalPicker` component supporting both modes and both UI variants from the start: inline 2-character debounced type-ahead with two-line result rows (display name + sub-label) and a popup dialog with type-filter chips. A small Zustand `directory-store` caches `directory.status` for the lifetime of the page so all picker instances on a page share one network call.
- The Assign Owner dialog migrated to `PrincipalPicker(multiple=false, accepts=['user'])`. The change is purely UI; the API payload still carries `user_email` as a plain string.
- Existing rows already in the database render as plain badges with no error decoration. The picker honours an optional `disabled` prop and works inside the surrounding form/RHF where applicable.
- Graceful degradation: if Graph is unreachable mid-session, the picker silently switches to manual-entry behaviour for the rest of the session.

### Acceptance criteria

- [ ] An admin can pick a UC HTTP Connection in Settings → Directory, hit Test, and see a success toast when credentials are valid; an authentication or 4xx/5xx response surfaces a destructive toast with a short error message.
- [ ] `GET /api/directory/status` returns `configured: false` until both `DIRECTORY_PROVIDER_TYPE` and `DIRECTORY_UC_HTTP_CONNECTION_NAME` are set; clearing either flips the response back to `false`.
- [ ] `GET /api/directory/search?q=ali&types=users` returns at least one `Principal` with `type: 'user'`, `id` matching a UPN/email, `display_name`, and a `sub_label` distinct from `display_name`. The same response shape is returned for `types=groups`.
- [ ] OData-injection probes (a single quote in `q`) are escaped server-side and never forwarded raw to Graph.
- [ ] In Assign Owner, with the directory configured, typing two characters opens a dropdown of two-line rows; picking one creates a non-editable badge whose tooltip shows the underlying email/UPN.
- [ ] In Assign Owner, with the directory not configured, typing a value and pressing Enter / Tab / comma turns the value into a badge; clicking the badge reverts it to editable text and re-confirming saves it again.
- [ ] An owner row created before the directory was configured renders as a plain badge in the Owner panel and can still be removed; no error icon, no console error.
- [ ] Killing network access to Graph mid-session causes the picker to log once and accept manual input for the rest of the session, without breaking the form.
- [ ] Existing API consumers calling the Assign Owner endpoint with a plain `user_email` string still succeed; backend payload is unchanged.
- [ ] Adding a stub second provider (e.g. an in-memory test double) requires no changes to `DirectoryManager` or routes — only registering a new `DirectoryProvider` implementation. Verified via a backend unit test.
- [ ] Backend unit tests cover `DirectoryManager` dispatch, OData escaping, `Principal` normalisation for users and groups, and `test()` happy/error paths against a mocked `serving_endpoints.http_request`.
- [ ] Frontend tests cover both `PrincipalPicker` modes (type-to-badge / click-to-edit / X-to-remove for unconfigured mode; debounced 2-char trigger / two-line rows / tooltip-shows-sub-label / X-to-remove for configured mode) and the `accepts` filter narrowing the search request.

---

## Phase 2: Multi-principal RBAC fields (Roles, Entitlements, Comments)

**User stories**: 20 (Roles `assigned_groups` + `assigned_users`); 21 (Entitlements persona groups); 27 (Comment audience)

### What to build

The hardest exercise of the picker — multi-pick, mixed user/group, and (in Roles' case) co-existing with the existing individual-user-role-assignment work. After Phase 2, the picker has been validated against every interaction shape it will ever see (single, multi, mixed types, groups-only). All later phases are mechanical.

The slice covers:

- The Roles form dialog: `assigned_groups` migrates from comma-separated text to `PrincipalPicker(multiple=true, accepts=['group'])`. `assigned_users` (already specified by the individual-user-role-assignment PRD, may or may not be merged at the time this lands) uses `PrincipalPicker(multiple=true, accepts=['user'])`. Both fields persist as `List[str]` of display names / emails.
- The Entitlements page: persona groups field replaces its hard-coded demo `Select` with `PrincipalPicker(multiple=true, accepts=['group'])`, sending a `List[str]` of group display names to the existing endpoint.
- The Comment composer: the audience field gains a `PrincipalPicker(multiple=true, accepts=['user','group'])` alongside (not replacing) the existing team / role checkbox lists. Picked users are emitted as plain emails; picked groups are emitted as plain group names; existing `team:*` / `role:*` tokens from the checkbox lists still flow through unchanged.
- Permission gates and existing audit/notification behaviour for each field are preserved. No new backend routes are added; existing PUT/POST endpoints accept the same payload shapes they already do.

### Acceptance criteria

- [ ] In Roles, an admin can add and remove groups from `assigned_groups` via the picker; after save, group membership-based authorization continues to work as before.
- [ ] In Roles, when both groups and users are assigned, the OR-semantics from the individual-user-role-assignment PRD continue to apply (a user matches the role via groups OR direct user membership).
- [ ] In Entitlements, a persona's group list can be added to and removed from via the picker; the existing `PUT /api/entitlements/personas/{id}/groups` endpoint accepts the same body shape.
- [ ] In Comments, an audience containing a mix of users, groups, teams (`team:*`), and roles (`role:*`) round-trips correctly; the existing notification fan-out for team/role tokens is unaffected.
- [ ] Picker tooltips on selected badges in all three places expose the underlying email / GUID for users / groups.
- [ ] Pre-existing Roles `assigned_groups` strings, persona groups, and comment audiences still render and save without any UI breakage.
- [ ] Frontend tests cover at least one form per page: a multi-pick + remove flow with the directory configured, and a multi-pick + remove flow with the directory not configured.

---

## Phase 3: Reviews, MDM, Tags, Teams, team-member dialogs

**User stories**: 22 (Data Asset Review reviewer_email); 23 (MDM reviewer); 24 (Tag ACL group_id); 25 (Teams `member_identifier`); 29 (Data product + Data contract team-member dialogs)

### What to build

The remaining "boring" single-user and group-only fields. No new architecture; mostly mechanical migration.

The slice covers:

- Create-Review-Request and Data-Asset-Review detail flows: `reviewer_email` becomes `PrincipalPicker(multiple=false, accepts=['user'])`. Backend payload and notification behaviour unchanged.
- MDM Create-Review dialog: `reviewer_email` becomes `PrincipalPicker(multiple=false, accepts=['user'])`. Same as above.
- Tag-namespace permissions: `permissionForm.group_id` becomes `PrincipalPicker(multiple=false, accepts=['group'])`. Backend ACL contract unchanged.
- Teams form dialog: `member_identifier` switches between `accepts=['user']` and `accepts=['group']` based on the existing `member_type` toggle in the same row, so a single picker instance handles both shapes by reacting to the surrounding form state.
- Data product team-member dialog: the `username` (email-or-handle) field becomes `PrincipalPicker(multiple=false, accepts=['user'])`. Backend payload still carries `username`.
- Data contract team-member dialog: the email/username field becomes `PrincipalPicker(multiple=false, accepts=['user'])` and continues to populate both `email` and `username` on submit if the existing endpoint requires both.

### Acceptance criteria

- [ ] All five surfaces accept picker output and round-trip the principal through their existing endpoints with no payload-shape change.
- [ ] In Teams, switching `member_type` from `user` to `group` resets the picker's `accepts` filter without losing form state for the other row fields.
- [ ] Tooltips on selected badges across all five surfaces expose the underlying identifier as required by the disambiguation rule.
- [ ] Existing reviewer assignments, MDM reviews, tag permissions, team rosters, and product/contract team members continue to render and save identically when the directory is not configured.
- [ ] Frontend tests cover at least Reviews + MDM (single-user) and Teams (type-switching) flows.

---

## Phase 4: Workflow Designer custom-principals + Data Contract Wizard wiring

**User stories**: 26 (Workflow recipients/approvers via "Custom principals" toggle); 28 (Data-contract wizard owner / stakeholders / groups / primary support email)

### What to build

The two trickier integrations, intentionally last:

- The Workflow Designer notification step recipients and approval step approvers each gain a "Custom principals…" toggle. When off, the existing role-based `Select` (and the `requester` / `owner` literals) is the only control — exactly today's behaviour. When on, an additional `PrincipalPicker(multiple=true, accepts=['user','group'])` appears alongside the role select, and any picked principals are appended to the same `recipients` / `approvers` list the backend already supports as email/group literals. No backend changes; the gap closed is purely UI.
- The Data Contract wizard placeholder fields (`dc-owner`, stakeholders, groups, primary support email — currently rendered but unwired to submit) are wired up. Each placeholder is replaced with `PrincipalPicker` configured for the appropriate `multiple` and `accepts`, and its value is included in the wizard's submission payload so the data is actually persisted.

### Acceptance criteria

- [ ] In the Workflow Designer notification step, toggling "Custom principals" on reveals a picker; picked emails and group names are sent in `recipients` alongside any role/literal entries from the role select; the existing role/literal entries continue to work without the toggle.
- [ ] In the Workflow Designer approval step, the same toggle works for `approvers` with the same semantics.
- [ ] Workflow execution against a custom-principal recipient continues to fan out via the existing notification path (no new backend logic).
- [ ] In the Data Contract wizard, owner / stakeholders / groups / primary-support-email values entered via the picker survive the entire wizard flow and appear on the submitted contract payload.
- [ ] No regression to the wizard's existing summary screen or to data contracts created via the inline / basic forms.
- [ ] Frontend tests cover the workflow designer toggle behaviour and the wizard end-to-end submit including a populated picker field.

---

## Out of plan (explicit non-goals for v1)

- A second concrete `DirectoryProvider` (Okta, Ping, etc.). The abstraction is in place from Phase 1; adding a new provider is a future phase that touches only the backend.
- Service principal lookups (reserved as a future expansion of `Principal.type`).
- Storage migration of the existing string fields to a structured `Principal` record.
- Bulk re-validation of pre-existing principals against the directory.
- OBO / delegated Graph queries.
- User profile photos, manager hierarchy, group membership traversal.
- Replacing the existing role / team `Select`s in the workflow designer (the Phase 4 toggle is additive only).

## PRD amendment (out-of-band, not a phase)

After this plan is approved, a separate small PR will amend `docs/prds/prd-entra-id-graph-integration.md` with a "Generalisation: Directory provider abstraction" section that:

- Renames the manager / routes / settings keys in the PRD to match this plan.
- Documents the `DirectoryProvider` interface and the v1-Entra-only scope.
- Keeps the story content (and the disambiguation rule) intact.
