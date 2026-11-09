# PRD: Large-account scale, async importers, and UC domain sync

## Problem Statement

A large enterprise customer running Ontos against a big Unity Catalog estate has surfaced a cluster of related limitations. Individually each is a papercut; together they make Ontos hard to operate at their scale and block a clean "govern what's already in UC" workflow.

1. **The Schema Importer silently caps children at 500.** Browsing (and the import collection pass) fetch at most 500 assets per path via a hardcoded `ListAssetsOptions(limit=500)`. Schemas or catalogs with more than 500 children silently lose the overflow — the extra objects are never fetched, there is no "load more", and nothing tells the operator the list is truncated. On a large account this quietly hides real assets.

2. **The Schema Importer runs synchronously and blocks the UI.** `execute_import` (and preview collection) run inside the HTTP request, fetching per-asset metadata as it creates each Ontos asset. On a large estate this takes minutes and the UI is blocked with no progress and no safe way to walk away. There is no size detection, no background option, and no completion signal.

3. **There is no operator-facing documentation for using the Ontos MCP server with Genie.** The MCP server exists and exposes tools, and the handbook explains Ask Ontos vs MCP conceptually, but there is no concrete "connect Genie / an external agent to Ontos MCP" setup guide (token creation, scopes, endpoint registration, worked example).

4. **Approving a role access request does not grant the role.** A user without a matching app role can request access, and an approver can approve it, but approval only logs and notifies — it never assigns the user to the role. The code comment states assignment "should be handled via external ITSM process", so the approve action is effectively a no-op for access. The requester believes they were granted access and still cannot use the feature.

5. **Domains cannot be synced with Unity Catalog.** UC has a first-class domains concept (a flat list — UC domains have no parent), but Ontos neither imports UC domains nor exports Ontos domains to UC. Ontos domains support a parent/child hierarchy; the customer wants to seed Ontos domains from their UC domains (choosing a root under which the flat UC list becomes one level of children) and, in the other direction, publish Ontos domains back to UC following a configurable level-to-UC-object mapping.

6. **Importer lists are not sorted.** The Schema Importer browse tree renders assets in whatever order the connector/API returns them, which is not alphabetical. On large lists this makes objects hard to find and makes truncation (item 1) even more confusing. The same unsorted behavior applies to the domain importer introduced in item 5.

## Solution

Ship a coordinated batch that makes Ontos operable at large-account scale. Each item is independently shippable and sliced into its own issue; this PRD is the umbrella and records the cross-item decisions and dependencies.

- **Configurable fetch limit (item 1).** Replace the hardcoded `500` with a General Settings value (`schema_import_child_limit`), bounded by the connector contract's existing `1..10000` range, defaulting to today's `500` so behavior is unchanged until an admin raises it. Surface an explicit "results truncated at N" signal on the browse response so operators know when they are hitting the cap rather than seeing the whole estate.
- **Async Schema Importer (item 2).** Detect estate size up front (reuse the preview collection count). Below a threshold, keep the current synchronous path. At or above it, offer a background run — user-selectable between an **in-app background thread** (medium jobs) and a **Databricks Job** (very large jobs) — reusing the existing `JobsManager` progress-notification pattern and the `JOB_PROGRESS` notification type. Progress and completion are reported through the existing notification bell (polling), including a terminal success/failure notification.
- **Ontos MCP + Genie documentation (item 3).** Extend the existing handbook with a concrete, worked "connect Genie / external agents to Ontos MCP" guide: creating an MCP token with the right scopes, registering the `/api/mcp` endpoint, and a Genie-specific example. Docs-only; no code change.
- **Role approval actually grants access (item 4).** On approval, assign the requester to the role. This depends on an individual-user-to-role assignment mechanism (`assigned_users`), specified in the existing `prd-individual-user-role-assignment.md`, which is **not yet implemented**. This PRD makes that dependency explicit: item 4 lands the approval-grant wiring on top of `assigned_users`, or delivers a minimal `assigned_users` write path if that PRD has not shipped first.
- **Domain sync with UC (item 5).** Add bidirectional domain sync mirroring the Schema Importer's dual sync/async model. **Import**: read the flat UC domain list, place them under an operator-chosen root Ontos domain as a single level of subdomains (one extra level only). **Export**: publish Ontos domains to UC following a configurable level-to-UC mapping (e.g. levels 1–2 → UC domains, level 3 → UC subdomains-as-tags where UC lacks native nesting). Provide both a synchronous UI path (akin to the Schema Importer) and an asynchronous Databricks Job path.
- **Alphabetical sorting (item 6).** Sort importer entries alphabetically. Applies to the Schema Importer browse tree and the new domain importer. The import **preview** dialog already sorts children alphabetically client-side; this item brings the **browse** surfaces in line.

## User Stories

### Configurable fetch limit (item 1)

1. As an **Admin** operating a large UC estate, I want to raise the Schema Importer's per-path child limit in General Settings, so that schemas with more than 500 tables show all their assets.
2. As an **Admin**, I want the limit bounded to a safe range (1–10000) with a clear default, so that I cannot set a value the connector contract rejects.
3. As a **Data Producer** browsing a schema whose children exceed the configured limit, I want a visible "results truncated at N" indication, so that I know the list is incomplete rather than assuming I am seeing everything.
4. As an **Admin** who has not changed anything, I want the limit to default to 500, so that upgrading changes no behavior until I opt in.

### Async Schema Importer (item 2)

5. As a **Data Producer** starting an import, I want Ontos to detect when the selection is large before it blocks, so that I am offered a background run instead of a frozen UI.
6. As a **Data Producer**, I want to choose between an in-app background run and a Databricks Job for large imports, so that I can match the execution model to the size of the job and my workspace's compute posture.
7. As a **Data Producer** who started a background import, I want to leave the page and see progress in the notification bell, so that I do not have to babysit the import.
8. As a **Data Producer**, I want a terminal success/failure notification when the import completes, including counts (created/skipped/errors), so that I know the outcome without re-running.
9. As a **Data Producer** running a small import, I want the current synchronous behavior to be unchanged, so that quick imports stay quick.
10. As an **Admin**, I want the size threshold that triggers the background offer to be sensible (and ideally configurable), so that the app behaves well across very different estate sizes.

### Ontos MCP + Genie docs (item 3)

11. As a **Platform Engineer**, I want a step-by-step guide to connect Genie to the Ontos MCP server, so that Genie can call Ontos tools without me reverse-engineering the endpoint.
12. As an **Admin**, I want the guide to specify exactly which MCP token scopes each documented use case needs, so that I grant least privilege.
13. As a **Developer**, I want a worked example (token creation → endpoint registration → a sample tool call), so that I can validate my setup end to end.

### Role approval grants access (item 4)

14. As an **Approver**, I want approving a role access request to actually assign the requester to the role, so that approval is not a silent no-op.
15. As a **Requester**, I want to be able to use the feature immediately after my request is approved, so that the "approved" notification matches reality.
16. As an **Admin**, I want approval to add the requester via the individual-user assignment mechanism rather than requiring an external group change, so that access is granted inside Ontos.
17. As an **Approver** who denies a request, I want denial to change nothing about assignments, so that denial is safe.
18. As a **Security-conscious Admin**, I want the grant recorded in the change log with who approved and who was granted, so that access changes are auditable.

### Domain sync with UC (item 5)

19. As a **Data Governor**, I want to import my Unity Catalog domains into Ontos under a root domain I choose, so that UC's flat domain list becomes an organized level of subdomains in Ontos.
20. As a **Data Governor**, I want to run the domain import synchronously from the UI for small sets and as a Databricks Job for large sets, so that the workflow matches the Schema Importer I already know.
21. As a **Data Governor**, I want to export Ontos domains to UC following a configurable pattern (which Ontos levels become UC domains vs UC subdomains), so that UC reflects our governance hierarchy.
22. As a **Data Governor**, I want the import to only add one extra level under my chosen root (UC domains have no parent), so that the imported structure is predictable and does not fabricate a hierarchy UC does not have.
23. As a **Data Governor** re-running an import, I want existing Ontos domains matched rather than duplicated, so that sync is idempotent.
24. As a **Data Governor**, I want a preview/dry-run of what a domain import or export will create or change, so that I can review before committing (mirroring the Schema Importer preview).

### Alphabetical sorting (item 6)

25. As a **Data Producer**, I want Schema Importer browse entries sorted alphabetically within each level, so that I can find objects quickly in long lists.
26. As a **Data Governor**, I want the domain importer entries sorted alphabetically, so that the domain list is scannable.
27. As a **Data Producer**, I want sorting to be case-insensitive and stable, so that ordering is predictable across refreshes and connectors.

## Implementation Decisions

### Cross-item: dual sync/async execution model

Item 2 and item 5 both introduce "small = synchronous UI, large = background" behavior. They share one model:

- **Size detection** reuses the existing preview/collection pass (for schema import) or the fetched UC domain count (for domain sync) to estimate work before committing.
- **In-app background thread** follows the pattern already used by `JobsManager._monitor_job_progress()` — a tracked worker that updates a `JOB_PROGRESS` notification with progress and terminal status.
- **Databricks Job** follows the existing `JobsManager` install/run/poll pattern (`workflow_job_runs` tracking table, `run_now`, background polling, `on_job_success`/`on_job_failure` triggers).
- **Status surface** is the existing notification bell (60s polling, visibility-aware). No websocket/SSE is introduced; that is out of scope.
- A new persisted record tracks in-app background import runs (state, counts, started/finished timestamps), analogous to `WorkflowJobRunDb`, so progress survives a page reload and the terminal notification can be reconstructed. Exact table shape is an implementation detail for the sliced issue.

### Item 1 — configurable child limit

- New General Settings key `schema_import_child_limit` stored in the existing key-value `app_settings` table (no schema migration; the repository is generic). Backed by a config field with an env default, loaded on startup, exposed via `GET /api/settings`, and validated on `PUT /api/settings` (positive integer, `1..10000` per the connector contract's existing `ListAssetsOptions` bound).
- `SchemaImportManager` reads the configured value instead of the hardcoded `500` at both fetch sites (browse and collection).
- The browse response gains a truncation signal (e.g. a boolean/`truncated_at` on the response) so the UI can show "showing first N; increase the limit in Settings". This is the one new field on the browse response; item 6's sorting rides on the same response.
- **No pagination.** Raising the cap is the mechanism; true continuation/paging past 10000 is explicitly a follow-up, not this PRD. The truncation signal makes the ceiling honest.

### Item 2 — async Schema Importer

- Below the threshold, `execute_import` stays synchronous and unchanged.
- At/above the threshold, the route returns immediately (202-style) with a run identifier; work proceeds on the chosen executor (in-app thread or Databricks Job).
- Progress notifications reuse `NotificationType.JOB_PROGRESS`; completion emits a terminal `SUCCESS`/`ERROR` notification carrying created/skipped/error counts and a deep link back to the import result.
- The threshold is a setting (reuse the General Settings plumbing from item 1) with a sensible default.

### Item 3 — MCP + Genie docs

- Extend `docs/handbook/mcp-and-ask-ontos.md` (or add a focused sibling doc it links to) with: token creation in Settings → MCP Tokens, the scope-to-use-case table, `/api/mcp` endpoint registration, and a Genie-specific worked example.
- Docs-only. No API, tool, or scope changes. If the worked example reveals a missing scope or ergonomics gap, that becomes a separate issue rather than expanding this one.

### Item 4 — role approval grants access

- **Dependency:** the grant requires an individual-user-to-role assignment mechanism. `prd-individual-user-role-assignment.md` specifies `assigned_users` on `app_roles` (JSON text column, case-insensitive email matching, OR-combined with `assigned_groups`) but it is **not implemented in the codebase today** (no `assigned_users` references exist in backend or frontend).
- Two acceptable orderings, decided at slicing time:
  - **Preferred:** item 4 depends on the individual-user-assignment work landing first, then adds the approval-grant wiring: on approve, add the requester's email to the target role's `assigned_users` and persist.
  - **Fallback:** if individual-user-assignment has not shipped, item 4 delivers the minimal `assigned_users` write path it needs (column + read-side matching + approval write), scoped down from the full UX in that PRD.
- The approval path (`handle_role_request_decision` in `settings_manager.py`) replaces the "no actual group assignment" log with a real assignment write, keeps the existing change-log entry (extended to record the grant), keeps the requester notification, and keeps marking the admin notification handled. Denial remains assignment-neutral.

### Item 5 — domain sync with UC

- **Model:** Ontos domains already support arbitrary parent/child nesting (`parent_id` self-reference). UC domains are flat.
- **Import:** operator picks a root Ontos domain (existing or new); the flat UC domain list is created as direct children (one level only) under that root; re-runs match by name to avoid duplicates; a preview/dry-run mirrors the Schema Importer preview.
- **Export:** a configurable level-to-UC mapping decides how Ontos levels project onto UC. Because UC domains are flat, deeper Ontos levels either map to additional UC domains or to a tag-based subdomain convention — the existing `DomainExportAdapter` (which already exports domains as UC *tags* with a `data_domain`/`data_domain_N` convention) and the `uc_tag_sync` `reconcile_tags` pattern are the prior art to extend rather than reinvent.
- **Execution:** synchronous UI path for small sets; Databricks Job for large sets, reusing the cross-item async model above.
- Databricks UC domain APIs are not yet used in the connector; the sliced issue includes confirming the SDK surface (list/create UC domains) and falling back to the tag convention where native domain nesting is unavailable.

### Item 6 — alphabetical sorting

- Sort within each level, case-insensitive, stable (`localeCompare`-style), matching the existing preview dialog's client-side sort.
- Preferred locus: sort in the backend `browse()` before returning nodes, so every consumer (Schema Importer tree, domain importer) gets consistent ordering and the truncation signal from item 1 reflects a sorted window. Containers and leaf assets are ordered within their groups; column nodes retain their metadata order unless trivially sortable.

## Testing Decisions

- **Item 1:** unit-test that `SchemaImportManager` uses the configured limit at both fetch sites; settings validation rejects out-of-range values; browse response reports truncation when the connector returns exactly the cap. Mirror existing settings-manager and connector test patterns (stub connector, in-memory session).
- **Item 2:** unit-test size detection selects sync vs background at the threshold boundary; a background run emits progress then a terminal notification with correct counts; the synchronous path is byte-for-byte unchanged below the threshold. Prefer patching the executor boundary over real threads/Databricks.
- **Item 3:** docs-only; validation is a reviewer walking the guide against a live MCP token. No automated test.
- **Item 4:** the critical path — approving a request adds the requester to `assigned_users` and a previously-unauthorized user then passes the permission check; denial leaves assignments unchanged; the change log records the grant. Mirror the authorization-manager tests referenced in `prd-individual-user-role-assignment.md`.
- **Item 5:** import places UC domains as one level under the chosen root and is idempotent on re-run; export honors the configured level mapping; preview creates nothing. Mirror `uc_tag_sync` reconcile tests.
- **Item 6:** browse response is alphabetically ordered within each level, case-insensitively; sorting is stable across repeated calls.

Tests are deterministic and require no Databricks credentials or network.

## Out of Scope

- **True pagination / continuation tokens** past the connector's 10000 ceiling (item 1 raises the cap and signals truncation; paging is a follow-up).
- **Websocket/SSE push** for import progress — the existing 60s notification polling is the status surface.
- **The full individual-user-assignment UX** (Principals column, badge-with-X inputs, SCIM autocomplete) — that is `prd-individual-user-role-assignment.md`; item 4 only needs the assignment write path.
- **Column-level sorting** semantics beyond leaf/container ordering.
- **New MCP tools or scopes** — item 3 is documentation only.
- **Native UC domain nesting** beyond what the UC API supports; deeper Ontos hierarchies fall back to the tag convention on export.
- **Bulk/CSV domain import** outside the UC sync path.

## Further Notes

- **Dependency graph:** item 4 depends on individual-user-to-role assignment (`assigned_users`) existing. Item 6 shares the browse-response change with item 1 and should land together or item-1-first to avoid two touches of the same response shape. Items 2 and 5 share the async execution model; building item 2 first establishes the pattern item 5 reuses.
- **Prior art to reuse, not reinvent:** `JobsManager` (background thread + Databricks Job + `workflow_job_runs` + progress notifications), `NotificationsManager`/notification bell (`JOB_PROGRESS`, polling), `DomainExportAdapter` + `uc_tag_sync.reconcile_tags` (UC domain-as-tag export), the generic `app_settings` key-value store (new numeric settings need no migration), and the import-preview dialog's existing alphabetical sort.
- **Related PRDs:** `prd-schema-importer-table-expand-recursion.md` (leaf/column tree semantics — this PRD does not change those), `prd-individual-user-role-assignment.md` (the `assigned_users` mechanism item 4 builds on), `prd-multi-domain-assignment.md` (domain association model context).
- Source of the reported issues: large-enterprise customer running Ontos against a big Unity Catalog estate.
