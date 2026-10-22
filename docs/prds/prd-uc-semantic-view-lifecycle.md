# PRD: UC Semantic View Lifecycle (Metric Views, Materialized Views)

## Problem Statement

Unity Catalog metric views are the semantic layer of a Databricks deployment: they hold the governed definition of a business measure (`SUM(amount)` over paid orders, by region and month). Ontos can now see them. #912 (phases 1 and 2, PR #1079) types them as `uc_metric`, parses their YAML spec into source, filter, joins, dimensions, measures and materialization, and shows it in the asset review editor. Everything after "see" is missing:

- **No semantic linkage.** A concept can be linked to a table or a column (`entity_semantic_links`, entity types `uc_table` and `uc_column`), but nothing in the UI offers it for a metric view or for one of its measures, and the review panel does not show existing links. Phase 3 of #912 and #30 (semantic assignment) ask for exactly this.
- **No governed change.** A measure definition changes when someone runs `ALTER VIEW ... AS $$ ... $$` in a SQL editor. Ontos has no draft, review, approval or audit for it, and the Databricks connector declares no write capability (`can_create_assets`, `can_update_assets` and `can_delete_assets` are `False`, `connectors/databricks.py`).
- **No drift signal.** When the definition in Unity Catalog changes after a review, nothing compares it with what was reviewed. #1079 found that Unity Catalog stores a normalized YAML (`fields` becomes `dimensions`, the top-level `comment` becomes the view comment, `display_name` and `format` are not kept in the stored text), so a plain text comparison would report drift that is not there.
- **Materialization is opaque.** A metric view with a `materialization` block is backed by a managed Lakeflow pipeline. Ontos shows the block (#1079) but not the refresh state, and does not warn about its constraints (the owner cannot change once materialized, group ownership is not supported).
- **No lifecycle.** A metric view imported through the schema importer becomes an Ontos asset of type View (`hasView`), because the ontology has no metric class (#1079, "Not in this PR"). It cannot be certified or deprecated as a metric view, and the lifecycle tag of #1025 would reach it through `uc_tag_sync`, which writes tags with `ALTER TABLE ... SET TAGS` for every object (`workflows/uc_tag_sync/uc_tag_sync.py`, `assign_tag`).

## Solution

Treat metric views (and, for visibility only, plain materialized views) as governed semantic objects, built on mechanisms Ontos already has:

1. **Semantic links on metric views and their fields**: reuse `entity_semantic_links` with `uc_table` for the metric view and `uc_column` for a dimension or measure (`catalog.schema.view.field`). No new entity type. The review panel and the asset page list and add links per field.
2. **Definition change requests**: a draft YAML is stored in Ontos, validated with the #1079 parser, reviewed through a process workflow and delivered through the existing Delivery modes: Indirect (a pull request with the YAML and the DDL, default), Direct (`ALTER VIEW ... AS $$ ... $$` executed by the app, opt-in) or Manual (a notification with the DDL). Ontos proposes; it does not apply without approval.
3. **Drift detection on the parsed spec**: the last approved definition is compared with the stored `view_definition` after both are parsed and normalized, so Unity Catalog's own rewriting is not reported as drift.
4. **Materialization visibility**: refresh state and schedule on the metric view page, and change-request checks for the documented materialization constraints.
5. **Lifecycle and evidence**: a Metric View asset type so a metric view can be certified and deprecated like other assets; lifecycle tags written with the right DDL for views; the YAML digest in the signed manifest of a product that exposes the metric view (#1023).

## User Stories

### Data modeller / steward

1. As a data modeller, I want to link a business concept to a metric view and to a specific measure, so that `Net Revenue` in the glossary points to the one governed definition.
2. As a data steward, I want to see, in the metric view panel, which concepts each dimension and measure is linked to, so that I can review the semantic coverage of the view.
3. As a data modeller, I want to propose a change to a measure's expression in Ontos and have it reviewed before it reaches Unity Catalog, so that governed definitions don't change silently.
4. As a reviewer, I want to see the proposed YAML as a diff against the current definition, with the parsed dimensions and measures, so that I can judge the change without reading raw YAML.

### Platform / owner

5. As a platform engineer, I want approved definition changes delivered as a pull request to the repository that owns our semantic layer, so that my team merges them through its normal process.
6. As the owner of a metric view, I want to be told when its definition in Unity Catalog no longer matches the last approved one, so that an out-of-band edit is noticed.
7. As the owner of a materialized metric view, I want to see when it was last refreshed and whether the refresh failed, so that I know whether queries are served from fresh data.

### Governance / consumer

8. As a data steward, I want to certify or deprecate a metric view, so that consumers know which definition to trust.
9. As an analyst querying a metric view directly, I want it to carry the lifecycle tag of the product that exposes it, so that I see when it is being retired.
10. As an auditor, I want the signed manifest of a product to include the digest of each metric view definition it exposes, so that I can prove which definition was in force at publication.

### Negative requirements

11. As an owner, I never want Ontos to change a metric view definition without an approved request.
12. As an owner, I never want a change request that Unity Catalog would refuse (for example, transferring a materialized metric view to a group owner) to reach the approval step.

## Implementation Decisions

### What #1079 already provides

- Typing: `TableType.METRIC_VIEW` maps to `UnifiedAssetType.UC_METRIC` (category SEMANTIC); the catalog tree types objects from the enum value.
- Definition: `common/metric_views.py` parses the YAML (`version`, `source`, `filter`, `joins` flattened with nested joins, `dimensions` with `fields` as a synonym, `measures`, `materialization`), with size and depth limits; `get_asset_metadata` carries it in `properties.metric_view`; `GET /api/data-asset-reviews/{request_id}/assets/{asset_id}/metric-view` returns the YAML and the parsed spec; `MetricViewDefinitionPanel` shows it.
- Verified on a real workspace in #1079: the Tables API returns `METRIC_VIEW` with the YAML in `view_definition`; the stored YAML is normalized as described in the Problem Statement; `SELECT *` on a metric view fails with `METRIC_VIEW_MISSING_MEASURE_FUNCTION`; changes appear after the 60 s cache of `CachingWorkspaceClient` expires.

This PRD builds on that and does not change the parser's contract.

### Semantic links (#912 phase 3, #30)

- A metric view is linked as `entity_type = uc_table`, `entity_id = catalog.schema.view`. A dimension or measure is linked as `uc_column`, `entity_id = catalog.schema.view.field`, where `field` is the `name` from the parsed spec. No new `EntityType` value and no migration (`models/semantic_links.py`, `db_models/semantic_links.py`).
- For a YAML 1.1 field without a `name` (allowed on Runtime 19+, where the name is derived from `expr`), the link uses the name Unity Catalog exposes for that column. Whether the Tables API returns the derived name is not verified; until it is, such fields are shown but can't be linked.
- The metric view panel lists each field's links and offers "Link concept"; the same links appear on the concept's linked objects.
- #734 (concepts-v2, open) adds a Map lane that links concepts to UC assets and a Deliver lane that pushes governed tags. This PRD uses the same link records, so a link made in either place is visible in both. Delivering a concept as a tag on a measure goes through #734's Deliver lane, not through this PRD.

### Definition change requests

- **Draft.** A change request stores the proposed YAML, the base definition it was written against (the parsed spec and the raw `view_definition` at the time), the requester and a justification. The proposed YAML must parse with `parse_metric_view_definition`; an unparseable proposal is refused with a coded error.
- **Pre-checks before review** (coded errors, translated in the UI):
  - the base definition still matches Unity Catalog (otherwise the requester rebases the draft);
  - the documented materialization constraints: owner unchanged when materialized, no group owner with materialization, no row filters, column masks or ABAC policies on a materialized source (the last one is only checked when the source is visible to the app);
  - field names unique, and every field linked by a concept still present (a removed field with links is a warning, shown in the review).
- **Review and approval** run through process workflows with a new trigger on the asset type, following the existing request triggers (`on_request_review` pattern) and the approval fallbacks already in place (owners, then Data Stewards and Admins; the requester can't approve their own request).
- **Delivery** reuses `DeliveryService` with a new change type `METRIC_VIEW_UPDATE`:
  - **Indirect (default)**: a YAML file and a DDL file (`ALTER VIEW <fqn> AS $$ ... $$`) are written to the configured Git repository and proposed as a pull request. This is the same "compile, never apply" stance as #1099 and #1100, and reuses the Git delivery of #1106 (and the Volume handling of #75) when they land.
  - **Direct (opt-in, `DELIVERY_MODE_DIRECT`)**: the app executes `ALTER VIEW <fqn> AS $$ ... $$` on a SQL warehouse after approval, then re-reads the definition and records the result. `DELIVERY_DIRECT_DRY_RUN` logs the statement instead.
  - **Manual**: a notification to the owner with the DDL to run.
- The connector capability flags stay `False`: write-back is a delivery, not connector CRUD.
- **Privileges.** Documented: creating a metric view needs `SELECT` on the source, `CREATE TABLE` and `USE SCHEMA` on the schema and `USE CATALOG`; `ALTER VIEW` replaces the full definition; ownership can be transferred to a group so its members can edit, except for materialized metric views. **Not verified**: which privilege `ALTER VIEW ... AS` requires on a metric view (the general rule for views is ownership). Direct delivery therefore requires the app service principal to own the metric view or belong to its owning group, and the pre-check reports when it doesn't.
- **Audit.** Every request, decision, delivery and its outcome is written to the audit log with the request id, the metric view FQN and the digests of the base and proposed definitions.

### Drift detection

- Ontos keeps, per metric view, the last approved definition (parsed and normalized) and its digest.
- Drift is computed by parsing the stored `view_definition` with the #1079 parser and comparing normalized specs, not raw text. Normalization: `fields` and `dimensions` as one list, keys sorted, whitespace in expressions collapsed, and the keys Unity Catalog does not keep in the stored text (`display_name`, `format`, top-level `comment`) excluded from the comparison.
- Drift is checked when the metric view metadata is read (cached like other metadata) and by the existing metadata refresh. It is shown on the metric view page and in open change requests; the owner gets one notification per detected change. Ontos never reverts a definition.
- Whether `display_name` and `format` are kept somewhere else in Unity Catalog (column metadata) is not verified. Until it is, an Ontos-authored `display_name` is delivered in the YAML but not compared.

### Materialization

- The parsed `materialization` block (#1079) is shown with its schedule, mode and materialized views.
- Refresh state is read from what Unity Catalog documents: `DESCRIBE EXTENDED <metric view>` shows "Refresh Information" with the status and a pipeline link. Which API field carries it for the SDK (`tables.get` properties or the pipeline API) is **not verified**; implementation starts by checking it on a workspace. The panel shows last refresh time, state and a link to the pipeline; a failed refresh is shown as a warning.
- Plain Unity Catalog materialized views (`MATERIALIZED_VIEW`) get the same read-only refresh panel when the same information is available. No change requests for them in this PRD.

### Contracts and products

- A metric view can be the asset behind an output port (`data_product_output_ports.asset_identifier` holds the FQN) and, as today, can be described in a contract's schema object. This PRD adds no contract field for it.
- Quality checks that issue `SELECT` against a metric view fail because measures need `MEASURE()` (verified in #1079). Contract quality rules on a metric view are out of scope; #1099's rule model and compilers would need a `MEASURE()`-aware target first.

### Lifecycle (#1025) and manifest (#1023)

- **Asset type.** A Metric View asset type (ontology class under the existing semantic category) so an imported metric view is an asset with its own type, status and certification (`AssetDb.status`, `certification_level`), instead of View. Existing imported metric views keep type View until re-imported or until a one-off retyping step (proposal; decided in implementation).
- **Deprecation.** A metric view asset follows the asset status values; deprecating a product follows #1025 and its tag reaches the metric view behind the product's output port.
- **Tag DDL.** `uc_tag_sync` writes `ALTER TABLE <fqn> SET TAGS` for every object, and views already take this path today: the job reads `source_type IN ('Table', 'View')` (`uc_tag_sync.py:368`, `:384`) and reconciles them as `TABLE` (`:964`, `:665`). Databricks documents `ALTER VIEW ... SET TAGS` for views. Whether Unity Catalog accepts `ALTER TABLE` for a view or a metric view is **not verified**; the lifecycle tag module of #1025 must use `ALTER VIEW` when `table_type` is `VIEW` or `METRIC_VIEW`, with a test.
- **Manifest.** #1023 already records, for a view behind an output port, a digest of `view_definition`. For a metric view the digest is computed on the stored (normalized) YAML, as returned by `tables.get`, so it is reproducible by a verifier. The manifest also records the digest of the last approved definition when one exists, so a reviewer can see whether the sealed definition was the approved one.

### Data model (proposal, migrations decided in implementation)

- `metric_view_change_requests`: id, metric view FQN, asset id, base definition (raw and digest), proposed YAML and digest, justification, status (`draft`, `in_review`, `approved`, `rejected`, `delivered`, `failed`), delivery mode, delivery reference (PR URL or statement id), requester, decided by, timestamps.
- `metric_view_baselines`: metric view FQN, last approved definition (normalized JSON) and digest, approved at, request id; drift state (`in_sync`, `drifted`, `unknown`) and last checked at.
- Semantic links: none (existing table).

### API surface (proposal)

- `GET /api/assets/{asset_id}/metric-view`: parsed spec, raw YAML, links per field, baseline and drift state, materialization and refresh state.
- `POST /api/assets/{asset_id}/metric-view/change-requests`: create a draft (YAML, justification); `GET` list; `GET /api/metric-view-change-requests/{id}` with the diff; `POST .../submit`, `POST .../cancel`.
- Decisions go through the existing approvals endpoints of process workflows.
- Errors are `detail = {code, message, params}` with the English message as fallback, translated in the UI.

### Modules

1. **Semantic links on fields**: panel and asset page, link and unlink per field, coordination with #734.
2. **Metric View asset type**: ontology class, importer mapping, status and certification.
3. **Baselines and drift**: normalization, digest, drift state and notification.
4. **Change requests**: draft, pre-checks, workflow trigger, review diff UI.
5. **Delivery**: `METRIC_VIEW_UPDATE` in Indirect, Direct and Manual modes.
6. **Materialization visibility**: refresh state panel for metric views and materialized views.
7. **Lifecycle and manifest hooks**: `ALTER VIEW` tags in `uc_tag_sync`, manifest digest fields.

## Testing Decisions

### Backend Tests (pytest)

| Area | Level | Cases |
|---|---|---|
| Field links | Unit | link and unlink a measure as `uc_column`; links listed per field; a field removed from the definition keeps its links and is flagged |
| Normalization | Unit | `fields` and `dimensions` compare equal; key order and expression whitespace ignored; `display_name`, `format` and top-level `comment` excluded; a changed `expr` is drift; a changed join condition is drift |
| Drift | Unit | in sync after delivery; drifted after an out-of-band change; unknown when the definition can't be read or parsed (#1079 limits) |
| Change request pre-checks | Unit | unparseable YAML refused; stale base refused; owner change on a materialized view refused; group owner with materialization refused; duplicate field names refused; removed linked field warned |
| Workflow | Integration | the trigger runs the approval; the requester can't approve; rejection keeps the baseline |
| Delivery | Unit (mocked SDK and Git) | Indirect writes YAML and DDL and opens a PR; Direct runs `ALTER VIEW ... AS` with the full YAML, re-reads and updates the baseline; dry run logs only; a failed statement leaves the request `failed` with a coded error and no baseline change; Manual sends the DDL |
| Audit | Unit | request, decision and delivery entries with digests |
| Tags | Unit | `uc_tag_sync` uses `ALTER VIEW` for `VIEW` and `METRIC_VIEW`, `ALTER TABLE` otherwise |
| Manifest | Unit | the metric view digest is computed on the stored YAML; the approved digest is included when present |

### Frontend Tests (Vitest + React Testing Library)

- Metric view panel: links per field, link dialog, drift badge, refresh state, en and pt.
- Change request: YAML editor with parse errors shown inline, diff of parsed specs, pre-check errors translated.

### End-to-end (manual)

On a workspace with a SQL warehouse (Runtime 17.3+), in a scratch schema:

1. Create a metric view with two dimensions and two measures; import it; check it is a Metric View asset.
2. Link a concept to the view and to one measure; check the links on the panel and on the concept.
3. Propose a change to a measure's expression; approve it as a Data Steward; with Indirect delivery check the pull request content; with Direct delivery check the new definition in Unity Catalog and the baseline.
4. Run `ALTER VIEW ... AS` outside Ontos; check drift is reported once, and not reported after a change that only renames `fields` to `dimensions`.
5. Add a `materialization` block; check refresh state and that a group-owner change request is refused.
6. Deprecate the product exposing the view; check the lifecycle tag on the metric view.
7. Publish the product with signing on; check the manifest digest of the view.
8. Drop everything created.

## Out of Scope

- Authoring metric views from scratch in Ontos (create and drop). Change requests start from an existing metric view.
- Contract quality rules on metric views (needs a `MEASURE()`-aware target, see #1099).
- Delivering concepts as tags or comments on measures (#734's Deliver lane).
- Change requests for plain materialized views and streaming tables.
- Querying or previewing metric view data in Ontos.
- BI tool semantic layers other than Unity Catalog metric views.

## Further Notes

### Implementation phases

| Phase | Modules |
|---|---|
| 1 | Semantic links on fields; Metric View asset type |
| 2 | Baselines and drift; materialization visibility |
| 3 | Change requests with Indirect and Manual delivery |
| 4 | Direct delivery; lifecycle and manifest hooks |

### Dependencies

- #1079 (open): parser, typing, panel. Everything here builds on it.
- #734 (open): shared semantic link records and the Deliver lane.
- #1106 (Git delivery as a pull request, child of #1099) and #75 (Git working copy in Databricks Apps): Indirect delivery.
- #1025 (lifecycle tags) and #1023 / #1024 (manifest): phase 4 hooks.

### Verified against

Code claims were checked against `development` at f786b917 (2026-10-19) and the #1079 branch. Databricks behavior comes from the metric view documentation (create, manage, YAML reference, materialization, query; checked 2026-10-19) and from the real-workspace validation recorded in #1079. Items marked **not verified** need a workspace check before implementation.

### Open questions

1. Which privilege `ALTER VIEW ... AS` requires on a metric view, and whether ownership by a group that includes the app service principal is enough for Direct delivery.
2. Where Unity Catalog keeps `display_name` and `format` once stored, and whether drift should compare them.
3. Which API exposes the refresh state of a materialized metric view to the SDK.
4. Whether the Tables API returns derived names for YAML 1.1 fields without `name`.
5. Whether existing metric views imported as View should be retyped automatically.
6. Whether Indirect delivery should target the same repository as #1106's enforcement artifacts or a separate semantic-layer repository.

### Relationship to existing PRDs and issues

- #912: phases 1 and 2 in #1079; this PRD is phase 3 and the write-back item.
- #30 (semantic assignment): delivered for metric views and their fields.
- #734 (concepts-v2): shared links and Deliver lane, no duplicate mechanism.
- #1099 / #1100: same "propose through Git, never apply without review" stance; no rule compilation for metric views here.
- #1025 (lifecycle) and #1023 / #1024 (manifest): hooks in phase 4.
- #180 (review panels): the metric view panel replaces the generic card.
