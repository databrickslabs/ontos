# PRD: Lifecycle Tag Automation and Deprecation Propagation

## Problem Statement

Ontos models lifecycle well: Data Products move through `draft → sandbox/proposed → under_review → approved → active → deprecated → retired` (`models/lifecycle.py`, see *Status values* for the exact sets). But deprecating a product is today a status change and nothing more. Everything that should happen *around* a deprecation is left to people.

Concretely:

- **No deprecation metadata.** There is no sunset date, no replacement product, no reason and no deprecation timestamp on Data Products or Data Contracts. Consumers learn that something is deprecated, but not until when, why, or what to use instead.
- **Subscribers get a generic notice.** `DataProductsManager.transition_status` already notifies subscribers when a product becomes `deprecated` or `retired` (`_notify_subscribers_of_status_change`), but with fixed text: no reason, sunset date or replacement, because none of them exist.
- **Refused subscriptions give no guidance.** `DataProductsManager.subscribe` only accepts `active` products, so subscribing to a deprecated or retired product fails with a generic status error that doesn't say what to use instead.
- **Lifecycle reaches Unity Catalog only by accident of configuration.** The `uc_tag_sync` job can already write `{PRODUCT.STATUS}` or `{CONTRACT.STATUS}` as a Unity Catalog tag through `tag_sync_configs`, but no default entry does so, the job runs on a 4-hour schedule, and a deprecation does not trigger a run. Direct Delivery does not apply tag changes at all (only `GRANT`/`REVOKE`). Analysts querying a table directly therefore have no reliable, timely signal that its product is being retired.
- **A table shared by several products gets an arbitrary product's values.** See *Shared tables*: the job keeps one product per table without a rule, so a status tag written today would be wrong as soon as two products with different statuses use the same table.
- **Certified products can be deprecated without review.** Nothing stops a direct transition of a certified product to `deprecated`.
- **No durable evidence.** Who deprecated a product, why, and with what replacement is only partially visible in the change log and not packaged as evidence (see the Signed Data Product Manifest PRD).

The building blocks exist: `on_status_change` / `before_status_change` / `on_request_status_change` workflow triggers, gates that block (#1012), rules that see the stored entity (#1019), approved status change requests that apply the status (#1028), notification steps, the built-in subscriber notice, the configurable `uc_tag_sync` job, `JobsManager.run_job`, and Compliance DSL tag actions that work (#1005). There is still no standard, end-to-end deprecation behavior. (`scheduled` process workflows are stored with a cron expression, but nothing in the app fires them yet: #941.)

## Solution

Ship a **standard deprecation lifecycle** for Data Products and Data Contracts, assembled from existing primitives:

1. **Deprecation vocabulary**: `deprecation_reason`, `sunset_date`, `replacement_product_id` (contracts: `replacement_contract_id`) and `deprecated_at`, captured by a deprecation dialog and required when moving to `deprecated`. Stored as first-class columns (see *Data model*).
2. **Lifecycle tag in Unity Catalog via `uc_tag_sync`**: a default `tag_sync_configs` entry that writes the lifecycle status to the tables behind output ports (`ontos_lifecycle_status`), with a defined rule for tables used by several products, and following the governed-tag conventions of #737 where governed tags are enabled. No new delivery mechanism.
3. **Timely propagation**: after a transition into or out of `deprecated` / `retired`, Ontos requests an on-demand `uc_tag_sync` run through `JobsManager.run_job` when the job is installed; otherwise the next scheduled run applies the tag. Failures are retried, recorded and shown to the owner.
4. **Approvals and notices**: deprecating a **certified** product or contract needs an approved status change request, enforced in the transition code. The guard is on by default and can be switched off per domain or product (`disabled_for`, see Approvals). The built-in subscriber notice carries the reason, sunset date and replacement; an owner notice and a sunset reminder are shipped as opt-in default workflows. Deleting a product with subscribers also notifies them (see *Deletion notice*).
5. **Subscription guidance**: subscribing to a `deprecated` or `retired` product stays refused (as today), and the error and the product page point to the replacement and sunset date.
6. **Evidence**: every deprecation and retirement is audited with reason, actor, sunset date and replacement; when the Signed Data Product Manifest is enabled, it is recorded as a `deprecated` / `retired` attestation.

## User Stories

### Producer / steward stories

1. As a Data Product owner, I want to provide a reason, a sunset date and a replacement product when I deprecate a product, so that consumers know what is happening and what to use instead.
2. As a Data Steward, I want deprecating a certified product or contract to require approval in every installation, so that trusted assets are not retired by accident.
3. As a Data Product owner, I want the product's tables and views in Unity Catalog to carry the lifecycle status as a tag shortly after I deprecate it, so that people who query them directly see the status.
4. As a Data Product owner, I want retiring (or reactivating) a product to update that tag, and to see on the product page when the tag could not be applied, so that the physical assets reflect the current lifecycle.
5. As a Data Product owner whose table is also used by another product, I want the tag not to claim the table is deprecated while the other product still offers it, so that its consumers are not misled.
6. As a Data Governance Officer, I want to edit the default deprecation workflows (recipients, reminder window) and the tag key used in Unity Catalog, so that the standard behavior matches our operating model.

### Consumer stories

7. As a Data Consumer subscribed to a product, I want to be notified when it is deprecated, with the sunset date and replacement, so that I can plan a migration.
8. As a Data Consumer, I want to be reminded before the sunset date, so that I do not miss the deadline.
9. As a Data Consumer, I want a refused subscription to a deprecated or retired product to tell me the sunset date and point me to its replacement, so that I do not build on something that is going away.
10. As a Data Consumer, I want the product page of a deprecated product to show the reason, sunset date and replacement.
11. As a Data Consumer (or the owner of a group or service principal subscribed on its behalf), I want to be told when a product I subscribe to is deleted, by whom and what replaces it, so that I do not find out when a pipeline breaks.

### Governance / audit stories

12. As an Auditor, I want each deprecation and retirement to record who, when, why, the sunset date and the replacement, so that lifecycle decisions are traceable.
13. As an Auditor, I want failed tag propagations and tag conflicts on shared tables to be recorded, so that I can tell when Unity Catalog did not reflect Ontos.

## Implementation Decisions

### Status values

Products and contracts share `EntityStatus` (`models/lifecycle.py`). The transition maps differ: contracts have no `sandbox`.

| Status | Data Product | Data Contract | Written to Unity Catalog | Precedence on a shared table (1 = wins) |
|---|---|---|---|---|
| `active` | yes | yes | yes | 1 |
| `approved` | yes | yes | yes | 2 |
| `under_review` | yes | yes | yes | 3 |
| `proposed` | yes | yes | yes | 4 |
| `sandbox` | yes | no | yes | 5 |
| `draft` | yes | yes | yes | 6 |
| `deprecated` | yes | yes | yes | 7 |
| `retired` | yes | yes | yes | 8 |

- Every status reaches Unity Catalog; a table shows the status of the product (or contract) that uses it, combined by the precedence column when several use it (see *Shared tables*).
- **`certified` is not a status.** Certification is a separate dimension, `certification_level` (an ordinal of the configured certification levels, `null` = not certified), with `certified_at` / `certified_by` / `certification_expires_at`. Migrations `a9_add_certification_to_data_products` and `b2_add_cert_pub_to_contracts` converted old `status = 'certified'` rows to `active` plus the top level. The `'certified'` entry still listed in `DataProductsManager.subscribe` is a leftover that no transition produces; the implementation removes it. "Certified product" in this PRD means `certification_level IS NOT NULL`.
- The governed tag's allowed values are exactly the eight statuses above, so no status can make the sync fail. Certification is not written to Unity Catalog by this PRD.

### Data model

- New nullable columns on `data_products` and `data_contracts`: `deprecation_reason` (text), `sunset_date` (date), `replacement_product_id` / `replacement_contract_id` (string id, same entity type), `deprecated_at` (timestamp). One Alembic migration following `.cursor/rules/11-database-migrations.mdc`.
- **Columns, not Compliance Template fields (#731).** Compliance Templates are admin-defined, with one active template per entity-type scope and no fixed semantics. Lifecycle automation (gates, reminders, subscription checks, banners, manifest attestations) needs fields whose meaning and presence are guaranteed in every deployment, can be queried and migrated, and should not compete with a customer's own template. The deprecation dialog reuses the typed-input components of #731. Reviewed in #1025 (maintainer agreement; Lars to confirm as owner of #731).
- The transition to `deprecated` requires `deprecation_reason`. `sunset_date`, when set, must not be before today's date in UTC; the dialog uses the same UTC date for its minimum, so the browser and the API agree near midnight.
- **Replacement rules.** `replacement_*` must:
  - reference an existing entity of the same type;
  - not be the entity itself;
  - not be `deprecated` or `retired`;
  - not create a cycle: following `replacement_*` from the replacement must never reach the entity, for chains of any length.

  A violation is rejected with a code and parameters (`replacement_not_found`, `replacement_is_self`, `replacement_deprecated`, `replacement_deprecated_replaced` with the end of its replacement chain, `replacement_retired`, `replacement_leads_back` with the chain), translated in the UI. These rules apply to the deprecation dialog and the status transition routes (`change-status`, and the status change request whose approval applies the status). Import keeps an exported history instead (see *Import*).
- **The update API doesn't write `status` (closed in STATUS_PR).** Today `PUT /api/data-products/{id}` and `PUT /api/data-contracts/{id}` store a `status` from the body directly, outside `transition_status`. Checked on a running instance (`development` @ f786b917): a Data Producer owning an `active` product with `certification_level` set moved it to `deprecated` with a plain `PUT` (no `X-Force-Update`; a status change isn't a breaking change for the impact analysis), while `change-status` on the same kind of product was blocked by an active `before_status_change` gate. With the `PUT`, no gate ran, no reason was asked for, and the only records were an `UPDATE` change log entry and audit entry. Contracts behave the same: an `active` contract moved to `deprecated` with a `PUT` carrying only `status`, and a certified one with `X-Force-Update`. Status changes go through `transition_status` only: a `PUT` whose `status` differs from the stored one is rejected with a code pointing to the status change routes.
- **Import.** ODPS/ODCS export these fields under `customProperties` (`ontosDeprecationReason`, `ontosSunsetDate`, `ontosReplacedBy`, `ontosDeprecatedAt`) and import maps them back. Anywhere else (the create API, the MCP tools) they are ignored, since the columns only change through a status transition.
  - **Import is create-only**, so it can't change the status or certification of an existing entity: an entity whose id exists is skipped, or imported as a copy with a new id ("Import duplicate IDs as new copies"), and the existing one is left as it was. Certification can't be imported either: a fresh import carrying `certificationLevel` creates an uncertified entity. Checked on a running instance: re-importing a certified `active` product with `status: retired`, with and without "Adopt IDs", left it `active` and certified; the copy was `retired` and uncertified.
  - **It restores the entity as it was exported**: a past sunset date, a `deprecated` or `retired` replacement (A deprecated toward B, then B deprecated) and a deprecated entity without a reason (exported before these fields existed) are kept, since rejecting them would break round-trips of Ontos's own exports.
  - **It rejects** an entity whose replacement is the entity itself or leads back to it, and a date that doesn't parse, with a code and parameters in the import result; the other entities of the file still import.
  - **Replacements in the same import.** Ids are regenerated unless "Adopt IDs" is on (off by default, and only for roles allowed to adopt ids), so a replacement is looked up first among the entities of the same import, by the id the file gives them, and linked once the whole import exists, whatever the order of the entities. A replacement that isn't in the target is not linked, and the import result notes it on the created entity rather than failing it.
  - The `CREATE` change log entry of an imported product or contract records its lifecycle fields; a replacement linked after the import is recorded as an `UPDATE`. Like any create, an import accepts the entity's status as given; the certified guard concerns transitions of existing entities.
- Moving `deprecated → active` (already allowed) clears `deprecated_at` and `sunset_date`; the previous values remain in the audit trail.

### Lifecycle tag in Unity Catalog

- Ship a default, enabled `tag_sync_configs` entry in `workflows/uc_tag_sync/uc_tag_sync.yaml`: `entity_type: data_product`, `tag_key_format: ontos_lifecycle_status`, `tag_value_format: {PRODUCT.STATUS}`. A `data_contract` entry with the same key and `{CONTRACT.STATUS}` ships disabled. The key is under the `ontos_` prefix the job reconciles, like the existing default keys.
- When governed tags are enabled (convention from #737), the key is created as a governed tag with the allowed values of *Status values*.
- After a lifecycle transition into or out of `deprecated` / `retired`, the transition hook calls `JobsManager.run_job` for the installed `uc_tag_sync` job, resolved from `workflow_installations` (debounced, at most one pending run). If the job is not installed or not scheduled, the tag is only updated by the next scheduled run: up to 4 hours with the default schedule, and never if the job is not installed. The product page says which case applies.
- Required privilege for the job's identity on target objects: `APPLY TAG`, documented next to `docs/decisions/uc-grants-for-app-sp.md`.

### Shared tables

**What the code allows today (verified against `development`):**

- An output port names its table in `data_product_output_ports.asset_identifier` (`db_models/data_products.py`, `OutputPortDb`): indexed, not unique, and `contract_id` is optional with no foreign key. Nothing stops two products, or two output ports, from naming the same table.
- A contract's schema object names its table in `data_contract_schema_objects.physical_name`, also not unique across contracts, and an asset can implement a contract through `entity_relationships` (`implementsContract`).
- `uc_tag_sync` reaches products only through a contract: `read_contracts_and_links` joins output ports on `op.contract_id = c.id AND op.asset_identifier = o.physical_name`, and `read_assets_and_links` does the same for assets (`workflows/uc_tag_sync/uc_tag_sync.py`). An output port without a contract is never tagged.
- When several products match one schema object, `build_dataset_tag_infos` keeps the first row (`setdefault` per `object_id`, and the query has no `ORDER BY`); when several contracts name the same table, `merge_dataset_tag_infos` keeps the last one per FQN. So today the existing `ontos_product_name` / `ontos_contract_name` tags of a shared table already come from an arbitrary product or contract, and a status tag would flip between runs or be wrong.

**Rule:**

- The job collects, per table FQN, every product whose output port names it (through a contract or directly by `asset_identifier`, which adds a query for ports without a contract) and, when the `data_contract` entry is enabled, every contract whose schema object or implementing asset names it.
- `ontos_lifecycle_status` carries the status with the best precedence among them (*Status values*). A table is only tagged `deprecated` when every product and contract using it is `deprecated` or `retired`, and only `retired` when all of them are `retired`. Retiring product A therefore never removes the `active` tag that product B still needs.
- When the users of a table have different statuses, the job records a conflict: the FQN, each product or contract with its status, and the value written (see *Failures and drift*). The product page of each of them shows that the table is shared and which value Unity Catalog carries.
- The single-valued tags `ontos_product_name` / `ontos_contract_name` keep one value per table; with this rule they pick the product or contract that decided the status (ties broken by name), so they are at least deterministic. Multi-valued product tags are not part of this PRD.

### Failures and drift

- **Retries.** Each `ALTER ... SET TAGS` / `UNSET TAGS` is attempted up to 3 times within a run (backoff 2 s, 10 s) for transient errors. Permission errors (`APPLY TAG` missing) and missing tables are not retried. Whatever still fails is retried by the next run, scheduled or on-demand.
- **Record.** The job writes one row per table and tag key it manages to a new `uc_tag_sync_results` table (FQN, key, desired value, contributing products and contracts with their statuses, outcome `applied` / `failed` / `conflict`, error text, attempted at), in the same Lakebase database it already reads. Failed runs also stay in `workflow_job_runs` (`result_state = FAILED`; the job exits non-zero when any tag failed) and keep the existing admin notification.
- **What the owner sees.** The product page lists the tables of its output ports with the lifecycle tag Unity Catalog should carry, the last outcome and, for `failed`, the error (shown as text for admins and owners only). When an on-demand run ends with a failure for one of the product's tables, the product owners get a notification with a code and parameters (`lifecycle_tag_failed`, FQN, status).
- **Drift.** Reverse synchronization (Unity Catalog → Ontos) is out of scope. A lifecycle tag edited or removed directly in Unity Catalog is overwritten by the next run (`reconcile_tags` compares the current value and upserts the desired one), and the overwrite is recorded as `applied` with the previous value. Until then, and when the job is not installed, Unity Catalog can show a status that Ontos no longer has: for example a deprecated product shows `active` for up to 4 hours with the default schedule if no on-demand run happens. #737 shows the pattern (Asset Review-gated inbound) if reverse sync is added later.

### Approvals and notices

- **Certified deprecation guard (enforced, not a workflow).** `transition_status` of products and contracts rejects a direct transition to `deprecated` when `certification_level` is set, with the code `certified_deprecation_requires_approval`. The only way through is `POST /api/data-products/{id}/request-status-change` (contracts: the equivalent route) and the Status Change Request workflow (`on_request_status_change`), whose approval applies the status (#1028) through a path the guard accepts. Approval is by a role with Admin on the feature (default: Data Governance Officer). This holds in every installation, with no admin action. The guard is on by default and can be switched off per domain, data product or data contract with the same `disabled_for` setting status gates have (STATUS_PR, part of #1114): for an exempted entity a certified product or contract deprecates directly, and each skip is logged and audited (`GATE_SKIPPED`). The enforcement policy template of #1114 uses the same switch, so one mechanism decides where lifecycle gates apply. A deployment that wants a stricter rule can add `before_status_change` gates on top.
- **Subscriber notice** (no workflow): `_notify_subscribers_of_status_change` adds the reason, sunset date and replacement to the existing `deprecated` / `retired` notices, sent with `data.i18n` keys (#1074), so subscribers are told in every installation, in their language.
- **Owner deprecation notice** (`on_status_change`, to `deprecated`): notify owners and business owners (`entity_owner`, resolved by #1011) with reason, sunset date and replacement. The transition adds the lifecycle fields to the `on_status_change` payload (today `{name, status}`), so templates (`${entity.<field>}`) can use them.
- **Sunset reminder** (daily): notify subscribers of products whose `sunset_date` is within a configurable window (default 14 days). `scheduled` process workflows have no runner yet (#941; `JobsManager` schedules Databricks jobs only, and `AccessGrantsManager.check_and_process_expirations`, which fires `on_expiring`, isn't called), so the reminder needs one: a small in-app scheduler or a Databricks job.
- The owner notice and the reminder are shipped as default workflows (editable, duplicable, not deletable), consistent with the default workflow catalog in `src/docs/USER-GUIDE.md`. Like other event-driven defaults (#1016) they are created inactive; an admin enables them. Only the certified guard and the subscriber notice are on out of the box.

### Deletion notice

Today, deleting a data product removes its `data_product_subscriptions` rows silently: since #739 / #1146 the foreign key's `ON DELETE CASCADE` does it, and nobody is told. This is part of the lifecycle's subscriber notification.

- **Who.** Every subscriber of the product, read from `data_product_subscriptions` before the delete. A row with `on_behalf_of_type` / `on_behalf_of_value` (`group`, `service_principal`) is notified through its `subscriber_email`, the person who requested it, and the text names the group or service principal it was requested for (`on_behalf_of_value`); the implementation checks how `notify_subscribers` treats these rows today and aligns both notices. `user` rows notify `subscriber_email`. A person with several rows gets one notice. The user who deletes is not notified.
- **When.** After the delete commits, so a rolled-back delete (as in #739) notifies nobody. The recipients are collected before the delete, since the cascade removes the rows. A failed notification is logged and does not fail the delete.
- **Content.** Product name and version, who deleted it, the time, and the replacement (id and name, with a link) when `replacement_product_id` is set. The text is built from `data.i18n` keys with parameters (#1074), so each recipient reads it in their language. Name and version are captured before the delete, since the product no longer exists when the notice is read.
- **Deprecated and active products.** The same notice is sent in both cases. For a `deprecated` or `retired` product, subscribers already got the deprecation notice, and the deletion notice says it is now gone; the `sunset_date` and replacement are shown if set. For an `active` product there was no warning, so the text says so plainly and carries no sunset date. Deletion does not clear the audit record of the earlier deprecation.
- **Acceptance.** Deleting a product with three subscribers (one user, one group, one service principal) produces three notices with the product name and version, the deleting user, and the replacement when set; a delete that fails produces none; a product with no subscribers produces none and the delete still returns 204; the notice exists in every locale.

Open question for maintainers: should deleting a product that has active subscribers require it to be `deprecated` (or `retired`) first, so that subscribers always get the deprecation notice and a sunset date before the product disappears? This PRD does not assume it: the notice above works either way, and a stricter rule would block admins from removing a product created by mistake.

### Subscription guidance

- `DataProductsManager.subscribe` refuses products that are not `active`. For `deprecated` and `retired` products the error is sent with a code and parameters (sunset date, replacement id and name) and the English text as fallback.
- The Marketplace and product detail views show a deprecation banner (reason, sunset date, replacement link) for deprecated products.

### Evidence

- Deprecation and retirement write audit entries (`feature='data-products'` / `'data-contracts'`, `action='DEPRECATE' | 'RETIRE'`) with reason, sunset date, replacement and the request id when it came through an approved request, from the UI or the API. An import creates rather than transitions, so its `CREATE` change log entry carries the fields (see *Import*).
- When `MANIFEST_SIGNING_ENABLED` is on, the lifecycle hook records `deprecated` / `retired` attestations referencing the latest manifest (extension of the attestation types defined in the Signed Data Product Manifest PRD).

### Modules

1. **Lifecycle fields**: model, migration, API models, validation (including the replacement rules and the UTC sunset date), ODPS/ODCS mapping (import as described in *Import*), deprecation dialog.
2. **Certified guard**: transition check for products and contracts, request path accepted by the guard, and its `disabled_for` switch (the `PUT` status write and the switch for status gates are already in STATUS_PR).
3. **Lifecycle tag**: default `tag_sync_configs` entry, shared-table aggregation and ports without a contract, retries, `uc_tag_sync_results`, optional governed tag, on-demand job run after transitions, tag status on the product page.
4. **Notices**: subscriber notice content, owner notice workflow, sunset reminder runner.
5. **Subscription guidance**: error content, UI banner.
6. **Evidence**: audit details and manifest attestations.

The Compliance DSL tag actions, listed as a prerequisite in the first version of this PRD, are fixed by #1005.

## Testing Decisions

### Backend Tests (pytest)

| Module | Test Type | What to Test |
|---|---|---|
| Lifecycle fields | Unit | Deprecation requires a reason; a sunset date before today (UTC) is rejected, today (UTC) is accepted; reactivation clears fields; ODPS/ODCS round-trip keeps the fields |
| Replacement rules | Unit | Rejected: missing, self, `deprecated` (with its chain), `retired`, a two-entity cycle (A → B → A), a three-entity cycle; accepted: a live replacement and a chain without cycle; each with its error code and parameters |
| Import | Integration | A `deprecated` or `retired` replacement, a past sunset date and a missing reason are kept; a replacement later or earlier in the same file is linked, with and without "Adopt IDs"; a replacement not in the target is not linked and the created entity carries a note; self-replacement, a chain that leads back and an unparseable date reject that entity with its code and the others import; the `CREATE` change log entry carries the fields; a product created through the API ignores the `ontos*` properties; re-importing an existing id never changes it |
| Certified guard | Integration | A direct transition of a certified product to `deprecated` is rejected with `certified_deprecation_requires_approval`; the same for a contract; an approved status change request applies it; an uncertified product deprecates directly; a certified product in a domain the guard is switched off for deprecates directly and the skip is audited, while one in another domain is still rejected; a `PUT` that changes `status` is rejected, for products and contracts |
| Lifecycle tag | Unit | `build_desired_for_dataset` produces `ontos_lifecycle_status=<status>` from the default config (stubbed pyspark, following the `uc_tag_sync` tests of #737); two products on one table, one `active` and one `deprecated`: the table gets `active` and a conflict is recorded, in either row order; both `deprecated`: `deprecated`; one `deprecated` and one `retired`: `deprecated`; an output port without a contract is tagged; a transient error is retried, a permission error is not; a failure is recorded in `uc_tag_sync_results` and the job exits non-zero |
| Propagation | Integration | The transition hook requests one debounced job run; no run requested when the job is not installed; the owner gets `lifecycle_tag_failed` after a failed on-demand run |
| Notices | Integration | Subscriber and owner notices carry reason, sunset date and replacement with `data.i18n` keys; the sunset reminder selects products inside the window |
| Deletion notice | Integration | Deleting a product notifies each subscriber once, including `group`, `service_principal` and `user` rows, with name, version, deleter and replacement and `data.i18n` keys; a failed delete notifies nobody; a product without subscribers deletes with 204; a failing notification does not fail the delete; deleted `deprecated` and `active` products give the matching text |
| Subscription guidance | Integration (`TestClient`) | Deprecated and retired → 409 with code, sunset date and replacement |
| Migration | Integration | `alembic upgrade head` succeeds; single head |

Prior art: `test_workflow_triggers_publish.py`, `test_data_product_routes.py`, existing compliance tests, the status change request tests of #1028, and the `uc_tag_sync` tests from #737.

### Frontend Tests (Vitest + React Testing Library)

| Module | Test Type | What to Test |
|---|---|---|
| Deprecation dialog | Component | Requires a reason; the sunset minimum is today in UTC; the replacement picker excludes the entity itself and deprecated or retired entities; a cycle error from the API is shown translated |
| Certified product | Component | For a certified product, Deprecate opens the status change request instead of the direct transition |
| Deprecation banner | Component | Shows reason, sunset date and replacement link |
| Lifecycle tag status | Component | Shows applied, failed (with the error) and conflict (with the other products) for the output port tables |
| Subscribe flow | Component | Shows the sunset date and replacement when a subscription is refused |

### End-to-end (manual)

E2E is skipped in CI, so each implementation PR documents this path on a local instance with a workspace that has the `uc_tag_sync` job installed:

1. Create two products whose output ports name the same Unity Catalog table; make both `active`; certify one of them.
2. Deprecate the certified product from its page: the dialog asks for reason, sunset date and replacement and opens a status change request; the status stays `active`.
3. As a Data Governance Officer, approve the request from the notification: the product becomes `deprecated`, subscribers get the notice with reason, sunset date and replacement, the audit entry has the request id.
4. Check the tag in Unity Catalog (`SELECT * FROM system.information_schema.table_tags WHERE ...` or Catalog Explorer) after the on-demand run: the shared table still carries `active`, the product page shows the conflict.
5. Deprecate the second product directly (not certified): after the run the table carries `deprecated`.
6. Edit the tag in Unity Catalog by hand: the next run restores it.
7. Retire one product: the tag stays `deprecated` until both are retired.

## Out of Scope

- **Reverse synchronization (Unity Catalog → Ontos).** Changing the lifecycle tag directly in Unity Catalog does not change the product status; the next run overwrites it.
- **Automatic retirement on the sunset date.** Reaching `sunset_date` triggers reminders, not a status change.
- **Deprecating physical assets independently** of a product (asset-level lifecycle).
- **Certification in Unity Catalog.** `certification_level` is not written as a tag.
- **Marketplace (external) consumers.** Notifying Databricks Marketplace consumers belongs to #165.
- **Revoking existing access grants** on retirement. Grants stay until explicitly revoked.
- **New delivery mechanisms.** Lifecycle tags use the existing `uc_tag_sync` job; Direct Delivery is not extended.

## Further Notes

### Implementation phases

1. **Lifecycle fields and certified guard**: model, migration, validation, export/import mapping, deprecation dialog (draft PR #1042), and the certified guard (its own PR). The `PUT` status write and the per-domain switch for status gates are in STATUS_PR (the `PUT` finding is also tracked in PUT_ISSUE).
2. **Lifecycle tag**: default tag sync entry, shared-table rule, failure record, on-demand job run.
3. **Notices and subscription guidance**: notices, reminder runner, subscribe errors, banner.
4. **Evidence**: audit details and manifest attestations (depends on the Signed Data Product Manifest).

### Dependencies

- Merged: #1005 (Compliance DSL tag actions), #1011 (`entity_owner` recipients), #1012 (blocking gates), #1015 / #1016 (default workflows at startup), #1019 (rules on the stored entity), #1028 (approved status change requests apply the status), #1074 (notification i18n keys).
- Migration order: the lifecycle columns come last, as `b9_lifecycle_deprecation_fields` in #1042, after `b3_property_custom_props` (#1077, merged), `b4_compliance_run_error_code` (#1081), `b5_lifecycle_status_cleanup` (the fix that makes status change only through a transition), `b6_contract_item_position` (contract column and custom property order), `b7_workflow_step_results_kept` (step results kept when a step is removed) and `b8_estates_tables` (#146), so that only #1042 waits on this PRD.

### Open questions

- Should subscribing to a deprecated product be allowed with an explicit acknowledgement (today it is refused)?
- Should deleting a product with active subscribers require it to be `deprecated` or `retired` first (see *Deletion notice*)?
- Should retirement automatically unpublish the product (`publication_scope = none`)?

Settled in review of this PRD: lifecycle fields are columns, not Compliance Template fields (#731, Lars to confirm); the key is `ontos_lifecycle_status`, governed when governed tags are enabled (#737); the certified guard is enforced out of the box, applies to contracts, and can be switched off per domain or entity like any status gate (aligned with #1114).

### Relationship to existing PRDs and issues

- **PRD #86 (Unified Lifecycle Tracking)**: defines the status dimension this PRD builds on.
- **#731 / PRD #676 (Compliance Templates)**: typed governance fields and publish completeness gate; their input components are reused for the dialog.
- **#737 (Domains ↔ Unity Catalog governed tags)**: the governed-tag convention and `uc_tag_sync` changes this PRD aligns with.
- **Signed Data Product Manifest PRD**: deprecation and retirement become attestations when manifests are enabled.
- **#421 (Governance Event Stream)**: `DataProductDeprecated` is a Phase 1 event; the default workflows can become subscribers once the stream exists.
- **#165 (Marketplace provider)**: external consumer notification on deprecation.
