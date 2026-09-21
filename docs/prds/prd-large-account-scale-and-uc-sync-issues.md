# Issues — Large-account scale, async importers, and UC domain sync

Created on `databrickslabs/ontos`. PRD: `docs/prds/prd-large-account-scale-and-uc-sync.md`.

- Epic: **#763**
- #757 — configurable child limit (item 1)
- #758 — async Schema Importer (item 2)
- #759 — MCP + Genie docs (item 3)
- #760 — role approval grants access, bug (item 4)
- #761 — domain sync with UC (item 5)
- #762 — alphabetical sorting (item 6)

Dependency order: **#757 first** (settings plumbing + browse-response shape shared with #762) → **#758** (async model reused by #761) → **#761** → **#759/#760/#762** independent. **#760 depends on `assigned_users` from `prd-individual-user-role-assignment.md`.** The section headings below retain their original draft numbering (#1–#6 map to #757–#762 in order).

---

## EPIC — Large-account scale, async importers, and UC domain sync

**Template:** epic · **Labels:** `epic`, `enhancement`

**Sub-tasks**
- [ ] #1 Make Schema Importer child limit configurable (item 1)
- [ ] #2 Async Schema Importer with size detection + background run (item 2)
- [ ] #3 Document Ontos MCP with Genie (item 3)
- [ ] #4 Fix: approving a role access request must grant the role (item 4)
- [ ] #5 Domain sync with Unity Catalog — import + export (item 5)
- [ ] #6 Sort Schema/Domain Importer entries alphabetically (item 6)

**Problem Statement**
A large-enterprise customer running Ontos against a big Unity Catalog estate hit a cluster of scale limitations: the Schema Importer silently caps at 500 children, imports run synchronously and block the UI, there is no guide for using the Ontos MCP with Genie, role-access approvals don't actually grant access, domains can't be synced with UC, and importer lists aren't sorted. See PRD `docs/prds/prd-large-account-scale-and-uc-sync.md`.

**Proposed Solution**
Ship the six sliced items above. Cross-cutting decisions (dual sync/async execution model reusing `JobsManager` + notifications, generic `app_settings` for new numeric settings, `assigned_users` dependency for #4) are recorded in the PRD.

**Additional Context**
Reuses existing infrastructure: `JobsManager` (background thread + Databricks Job + `workflow_job_runs`), notification bell (`JOB_PROGRESS`, 60s polling), `DomainExportAdapter` + `uc_tag_sync.reconcile_tags`, generic `app_settings` key-value store.

---

## #1 — Make Schema Importer child limit configurable

**Template:** feature · **Labels:** `enhancement`, `settings`, `schema-importer`

**Problem statement**
The Schema Importer fetches at most 500 assets per path via a hardcoded `ListAssetsOptions(limit=500)` at two sites in `src/backend/src/controller/schema_import_manager.py` (browse ~L163, collection ~L698). Schemas/catalogs with >500 children silently lose the overflow — never fetched, no "load more", no truncation indication. On large estates this hides real assets.

**Proposed Solution**
- Add General Settings key `schema_import_child_limit` in the generic `app_settings` key-value table (no migration). Config field + env default (500), loaded on startup, exposed via `GET /api/settings`, validated on `PUT /api/settings` to `1..10000` (the existing `ListAssetsOptions` bound in `connectors/base.py`).
- `SchemaImportManager` reads the configured value at both fetch sites instead of `500`.
- Add a truncation signal to the browse response (e.g. `truncated`/`truncated_at`) so the UI can show "showing first N — raise the limit in Settings".
- Frontend: add the numeric field to General Settings (`components/settings/general-settings.tsx` + `app-settings-store`) and surface the truncation notice in the browse tree.
- Default 500 → no behavior change until an admin opts in.

**Additional Context**
No pagination — raising the cap is the mechanism; continuation past 10000 is an explicit follow-up. Shares the browse-response change with #6; land together or #1 first. Tests: manager uses configured limit at both sites; settings validation rejects out-of-range; browse reports truncation at the cap.

---

## #2 — Async Schema Importer with size detection and background run

**Template:** feature · **Labels:** `enhancement`, `schema-importer`, `jobs`

**Problem statement**
`execute_import` (and preview collection) run inside the HTTP request, fetching per-asset metadata while creating each Ontos asset. On a large estate this takes minutes and blocks the UI with no progress, no background option, and no completion signal.

**Proposed Solution**
- Detect estate size up front (reuse the preview/collection count). Below a configurable threshold, keep the current synchronous path unchanged.
- At/above threshold, return immediately with a run id and execute in the background, **user-selectable** between an **in-app background thread** (medium) and a **Databricks Job** (very large), reusing the `JobsManager` patterns (`_monitor_job_progress`, install/run/poll, `workflow_job_runs`).
- Progress via `NotificationType.JOB_PROGRESS`; terminal `SUCCESS`/`ERROR` notification with created/skipped/error counts + deep link. Status surfaces in the existing notification bell.
- Persist in-app background run state (analogous to `WorkflowJobRunDb`) so progress survives reload.
- Threshold is a setting (reuse #1 plumbing) with a sensible default.

**Additional Context**
Establishes the dual sync/async model reused by #5 — build this first. No websocket/SSE (60s polling is the surface). Tests: threshold boundary selects sync vs background; background run emits progress then terminal notification with correct counts; sync path unchanged below threshold; prefer patching the executor boundary over real threads/Databricks.

---

## #3 — Document how to use the Ontos MCP server with Genie

**Template:** feature · **Labels:** `documentation`, `mcp`

**Problem statement**
The Ontos MCP server (`routes/mcp_routes.py`, `POST /api/mcp`) exposes tools and the handbook (`docs/handbook/mcp-and-ask-ontos.md`) explains Ask Ontos vs MCP conceptually, but there is no concrete guide to connect Genie / an external agent: token creation, scopes, endpoint registration, or a worked example.

**Proposed Solution**
Extend `docs/handbook/mcp-and-ask-ontos.md` (or a focused sibling it links) with: creating an MCP token in Settings → MCP Tokens, a scope-to-use-case table (least privilege), registering the `/api/mcp` endpoint, and a Genie-specific worked example (token → registration → sample tool call). Docs-only.

**Additional Context**
No API/tool/scope changes. If the worked example reveals a missing scope or ergonomics gap, file that separately. Validation is a reviewer walking the guide against a live MCP token.

---

## #4 — Bug: approving a role access request does not grant the role

**Template:** bug · **Labels:** `bug`, `rbac`, `settings` · **Blocked by:** `assigned_users` from `prd-individual-user-role-assignment.md`

**Current Behavior**
A user without a matching app role requests access (`POST /api/user/request-role/{role_id}`), an approver approves (`POST /api/settings/roles/handle-request` → `handle_role_request_decision` in `settings_manager.py` ~L2278). Approval only logs, change-logs, and notifies — it never assigns the user to the role. The code comment (~L2345) says assignment "should be handled via external ITSM process". The requester gets an "approved" notification but still cannot use the feature.

**Expected Behavior**
Approving assigns the requester to the target role so they immediately gain access. Denial changes nothing. The grant is recorded in the change log (who approved, who was granted).

**Steps To Reproduce**
1. As a user with no matching app role, request access to a role.
2. As an approver, approve the request.
3. Observe the requester still lacks the role's permissions.

**Additional Context / Proposed fix**
Depends on an individual-user-to-role assignment mechanism (`assigned_users` on `app_roles`), specified in `prd-individual-user-role-assignment.md` but **not yet implemented** (no `assigned_users` references exist in the codebase). Two orderings:
- **Preferred:** land individual-user assignment first, then on approve add the requester's email to the role's `assigned_users` and persist.
- **Fallback:** deliver the minimal `assigned_users` write path here (column + read-side matching + approval write), scoped down from that PRD's full UX.

Replace the "no actual group assignment" log with the assignment write; keep change-log (extended to record the grant), requester notification, and admin-notification-handled marking. Tests: approving adds requester to `assigned_users` and a previously-unauthorized user then passes the permission check; denial leaves assignments unchanged.

---

## #5 — Domain sync with Unity Catalog (import + export)

**Template:** feature · **Labels:** `enhancement`, `domains`, `unity-catalog`, `jobs`

**Problem statement**
UC has a first-class domains concept (flat — no parent), but Ontos neither imports UC domains nor exports Ontos domains to UC. Ontos domains support parent/child nesting (`parent_id`). The customer wants to seed Ontos domains from UC domains and publish Ontos domains back to UC.

**Proposed Solution**
- **Import:** read the flat UC domain list; place them as direct children (one level only) under an operator-chosen root Ontos domain (existing or new); match by name on re-run to stay idempotent; provide a preview/dry-run mirroring the Schema Importer.
- **Export:** publish Ontos domains to UC following a configurable level-to-UC mapping (e.g. levels 1–2 → UC domains, level 3 → subdomains via the tag convention where UC lacks native nesting). Extend the existing `DomainExportAdapter` (`data_domain`/`data_domain_N` tag convention) and `uc_tag_sync.reconcile_tags` rather than reinventing.
- **Execution:** synchronous UI path for small sets; Databricks Job for large sets, reusing the #2 async model.
- Confirm the Databricks SDK UC-domain surface (list/create); fall back to the tag convention where native nesting is unavailable.

**Additional Context**
Reuses #2's async model — build #2 first. Prior art: `DomainExportAdapter`, `uc_tag_sync`, `data_domains` model (`parent_id`). Tests: import places UC domains as one level under the chosen root and is idempotent; export honors the configured mapping; preview creates nothing.

---

## #6 — Sort Schema/Domain Importer entries alphabetically

**Template:** feature · **Labels:** `enhancement`, `schema-importer`, `domains`, `ux`

**Problem statement**
The Schema Importer browse tree renders assets in connector/API order, not alphabetical. On large lists (and given the truncation in #1) this makes objects hard to find. The domain importer from #5 has the same need. Note: the import **preview** dialog already sorts children alphabetically client-side; the **browse** surfaces do not.

**Proposed Solution**
Sort within each level, case-insensitive, stable (`localeCompare`-style), matching the existing preview sort. Preferred locus: sort in the backend `browse()` before returning nodes so every consumer (Schema Importer tree, domain importer) is consistent and the #1 truncation window reflects a sorted list. Order containers and leaf assets within their groups; column nodes keep metadata order unless trivially sortable.

**Additional Context**
Shares the browse-response touch with #1 — coordinate. Tests: browse response is alphabetically ordered within each level, case-insensitively; sorting is stable across repeated calls.
