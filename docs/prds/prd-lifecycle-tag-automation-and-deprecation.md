# PRD: Lifecycle Tag Automation and Deprecation Propagation

## Problem Statement

Ontos models lifecycle well — Data Products move through `draft → sandbox/proposed → under_review → approved → active → deprecated → retired` (`models/lifecycle.py`) — but deprecating a product is today a status change and nothing more. Everything that should happen *around* a deprecation is left to people.

Concretely:

- **No deprecation metadata.** There is no sunset date, no replacement product, no reason and no deprecation timestamp on Data Products or Data Contracts. Consumers learn that something is deprecated, but not until when, why, or what to use instead.
- **Subscribers get a generic notice.** `DataProductsManager.transition_status` already notifies subscribers when a product becomes `deprecated` or `retired` (`_notify_subscribers_of_status_change`), but with fixed text: no reason, sunset date or replacement, because none of them exist.
- **Refused subscriptions give no guidance.** `DataProductsManager.subscribe` only accepts `active` (and `certified`) products, so subscribing to a deprecated or retired product fails with a generic status error that doesn't say what to use instead.
- **Lifecycle reaches Unity Catalog only by accident of configuration.** The `uc_tag_sync` job can already write `{PRODUCT.STATUS}` or `{CONTRACT.STATUS}` as a Unity Catalog tag through `tag_sync_configs`, but no default entry does so, the job runs on a 4-hour schedule, and a deprecation does not trigger a run. Direct Delivery does not apply tag changes at all (only `GRANT`/`REVOKE`). Analysts querying a table directly therefore have no reliable, timely signal that its product is being retired.
- **The declarative path is broken.** The Compliance DSL advertises `ASSIGN_TAG` / `REMOVE_TAG`, but `ComplianceManager` builds the `ActionContext` without a tag manager, so these actions currently fail with "Tag manager not available" (#948; fix proposed in #975).
- **Certified products can be deprecated without review.** There is no default gate requiring approval before a certified product is deprecated, and a `before_status_change` gate with an approval step can't provide one: since #985 such a gate blocks the transition while the approval is pending, and nothing applies the transition once it is approved.
- **No durable evidence.** Who deprecated a product, why, and with what replacement is only partially visible in the change log and not packaged as evidence (see the Signed Data Product Manifest PRD).

The building blocks exist — `on_status_change` / `before_status_change` / `on_request_status_change` workflow triggers, notification steps, the built-in subscriber notice, the configurable `uc_tag_sync` job and `JobsManager.run_job` — but there is no standard, end-to-end deprecation behavior. (`scheduled` process workflows are stored with a cron expression, but nothing in the app fires them yet.)

## Solution

Ship a **standard deprecation lifecycle** for Data Products (and the same fields for Data Contracts), assembled from existing primitives and aligned with work in flight:

1. **Deprecation vocabulary** — `deprecation_reason`, `sunset_date`, `replacement_product_id` (contracts: `replacement_contract_id`) and `deprecated_at`, captured by a deprecation dialog and required when moving to `deprecated`. Stored as first-class lifecycle fields (see *Data model* for why not as Compliance Template fields, #731).
2. **Lifecycle tag in Unity Catalog via `uc_tag_sync`** — a default `tag_sync_configs` entry that writes the product status to the physical assets of its output ports (`ontos_lifecycle_status = {PRODUCT.STATUS}`), following the governed-tag conventions introduced for domains in #737 where governed tags are enabled. No new delivery mechanism.
3. **Timely propagation** — after a transition to `deprecated`, `retired` or back to `active`, Ontos requests an on-demand `uc_tag_sync` run through `JobsManager.run_job` when the job is installed; otherwise the next scheduled run applies the tag.
4. **Notices and approvals** — the built-in subscriber notice carries the reason, sunset date and replacement; a default workflow notifies owners; deprecating a **certified** product goes through the status change request flow with an approval; a sunset reminder runs daily.
5. **Subscription guidance** — subscribing to a `deprecated` or `retired` product stays refused (as today), and the error and the product page point to the replacement and sunset date. Allowing a deprecated product with an explicit acknowledgement is an open question.
6. **Evidence** — every deprecation and retirement is audited with reason, actor, sunset date and replacement; when the Signed Data Product Manifest is enabled, it is recorded as a `deprecated` / `retired` attestation.

As a prerequisite, the Compliance DSL tag actions are fixed so that policies can also assign tags declaratively.

## User Stories

### Producer / steward stories

1. As a Data Product owner, I want to provide a reason, a sunset date and a replacement product when I deprecate a product, so that consumers know what is happening and what to use instead.
2. As a Data Steward, I want deprecating a certified product to require approval, so that trusted products are not retired by accident.
3. As a Data Product owner, I want the product's tables and views in Unity Catalog to carry the product's lifecycle status as a tag shortly after I deprecate it, so that people who query them directly see the status.
4. As a Data Product owner, I want retiring (or reactivating) a product to update that tag, so that the physical assets always reflect the current lifecycle.
5. As a Data Governance Officer, I want to edit the default deprecation workflows (recipients, gates, reminder window) and the tag key used in Unity Catalog, so that the standard behavior matches our operating model.

### Consumer stories

6. As a Data Consumer subscribed to a product, I want to be notified when it is deprecated, with the sunset date and replacement, so that I can plan a migration.
7. As a Data Consumer, I want to be reminded before the sunset date, so that I do not miss the deadline.
8. As a Data Consumer, I want a refused subscription to a deprecated or retired product to tell me the sunset date and point me to its replacement, so that I do not build on something that is going away.
9. As a Data Consumer, I want the product page of a deprecated product to show the reason, sunset date and replacement.

### Governance / audit stories

10. As an Auditor, I want each deprecation and retirement to record who, when, why, the sunset date and the replacement, so that lifecycle decisions are traceable.
11. As a Compliance Officer, I want Compliance DSL policies with `ASSIGN_TAG` / `REMOVE_TAG` to actually apply tags, so that tagging can also be enforced declaratively.

## Implementation Decisions

### Data model

- New nullable columns on `data_products` and `data_contracts`: `deprecation_reason` (text), `sunset_date` (date), `replacement_product_id` / `replacement_contract_id` (string id, same entity type), `deprecated_at` (timestamp). One Alembic migration following `.cursor/rules/11-database-migrations.mdc`.
- **Why first-class fields rather than Compliance Template fields (#731):** Compliance Templates are admin-defined, with one active template per entity-type scope and no fixed semantics. Lifecycle automation (gates, reminders, subscription checks, Marketplace banners, manifest attestations) needs fields whose meaning and presence are guaranteed in every deployment, and should not compete with a customer's own template. The deprecation dialog can still render these fields with the typed-input components introduced by #731. This is an explicit question for maintainers (see *Open questions*).
- Transition rules in `models/lifecycle.py` stay as they are; the transition to `deprecated` additionally requires `deprecation_reason`, and `sunset_date` must not be in the past. `replacement_*` must reference an existing, non-retired entity.
- Moving `deprecated → active` (already allowed) clears `deprecated_at` and `sunset_date`; the previous values remain in the audit trail.
- ODPS/ODCS export these fields under `customProperties` (e.g. `ontos:sunsetDate`, `ontos:replacedBy`) so round-trips preserve them; import maps them back.

### Lifecycle tag in Unity Catalog

- Ship a default, enabled `tag_sync_configs` entry in `workflows/uc_tag_sync/uc_tag_sync.yaml`: `entity_type: data_product`, `tag_key_format: ontos_lifecycle_status`, `tag_value_format: {PRODUCT.STATUS}` (and the equivalent `{CONTRACT.STATUS}` entry, disabled by default). The job already resolves the tables behind contract schema objects linked to product output ports and reconciles their tags; no job logic changes are needed for plain tags.
- When governed tags are enabled (convention from #737), the key is created as a governed tag with the allowed values `draft, sandbox, proposed, under_review, approved, active, deprecated, retired`, so values cannot drift.
- After a lifecycle transition into or out of `deprecated` / `retired`, the transition hook calls `JobsManager.run_job` for the installed `uc_tag_sync` job, resolved from `workflow_installations` (debounced, at most one pending run). If the job is not installed, the next scheduled run (every 4 hours by default) applies the change.
- Required privilege for the job's identity on target objects: `APPLY TAG`, documented next to `docs/decisions/uc-grants-for-app-sp.md`.
- Reverse synchronization (Unity Catalog → Ontos) is out of scope; #737 shows the pattern (Asset Review-gated inbound) if it is added later.

### Notices and default workflows

- **Subscriber notice** (no workflow): `_notify_subscribers_of_status_change` adds the reason, sunset date and replacement to the existing `deprecated` / `retired` notices, so subscribers are told in every installation.
- **Owner deprecation notice** (`on_status_change`, to `deprecated`): notify owners and business owners (`entity_owner`, resolved since #984) with reason, sunset date and replacement. The transition adds the lifecycle fields to the `on_status_change` payload (today `{name, status}`), because notification templates (`${entity.<field>}`) read the payload, not the stored entity.
- **Certified deprecation approval**: a `before_status_change` validation gate (no approval step) blocks a direct transition to `deprecated` when `certification_level` is set; it needs rules to see the stored entity (#992) and gates that block (#985). Deprecating a certified product then goes through `POST /api/data-products/{id}/request-status-change` and the Status Change Request workflow (`on_request_status_change`), approved by a role with `data-products` Admin (default: Data Governance Officer). Approving that workflow doesn't apply the requested status today: the executor has no completion handling for `on_request_status_change`. This PRD adds it.
- **Sunset reminder** (daily): notify subscribers of products whose `sunset_date` is within a configurable window (default 14 days). `scheduled` process workflows have no runner yet (`JobsManager` schedules Databricks jobs only, and `AccessGrantsManager.check_and_process_expirations`, which fires `on_expiring`, isn't called), so the reminder needs one: a small in-app scheduler or a Databricks job.
- Shipped as default workflows (editable, duplicable, not deletable), consistent with the default workflow catalog in `src/docs/USER-GUIDE.md`. With #989 the defaults are created at startup, but only request workflows (`on_request_*`) start active, so the owner notice, the gate and the reminder are created inactive until an admin enables them.

### Subscription guidance

- `DataProductsManager.subscribe` already refuses products that are not `active` / `certified`. For `deprecated` and `retired` products the error includes the sunset date and the replacement id.
- The Marketplace and product detail views show a deprecation banner (reason, sunset date, replacement link) for deprecated products.

### Compliance DSL fix (prerequisite)

- `ComplianceManager` passes an `EntityTagManager` implementation (backed by `TagsManager`) into `ActionContext`, so `ASSIGN_TAG` / `REMOVE_TAG` work for Ontos entities. Tagging Unity Catalog objects from policies is not part of this fix.

### Evidence

- Deprecation and retirement write audit entries (`feature='data-products'`, `action='DEPRECATE' | 'RETIRE'`) with reason, sunset date and replacement.
- When `MANIFEST_SIGNING_ENABLED` is on, the lifecycle hook records `deprecated` / `retired` attestations referencing the latest manifest (extension of the attestation types defined in the Signed Data Product Manifest PRD).

### Modules

1. **Compliance DSL tag actions fix.**
2. **Lifecycle fields** — model, migration, API models, validation, ODPS/ODCS mapping, deprecation dialog.
3. **Lifecycle tag** — default `tag_sync_configs` entry, optional governed tag, on-demand job run after transitions.
4. **Notices and approvals** — subscriber notice content, owner notice workflow, certified deprecation gate and status change request completion, sunset reminder runner.
5. **Subscription guidance** — error content, UI banner.
6. **Evidence** — audit details and manifest attestations.

## Testing Decisions

### Backend Tests (pytest)

| Module | Test Type | What to Test |
|---|---|---|
| Lifecycle fields | Unit | Deprecation requires a reason; past sunset dates rejected; replacement must exist and not be retired; reactivation clears fields; ODPS/ODCS round-trip keeps the fields |
| Lifecycle tag | Unit | `build_desired_for_dataset` produces `ontos_lifecycle_status=<status>` from the default config (stubbed pyspark, following the `uc_tag_sync` test approach introduced in #737); transition hook requests one debounced job run; no run requested when the job is not installed |
| Notices and approvals | Integration | Subscriber and owner notices carry reason/sunset/replacement; a direct transition of a certified product to `deprecated` is blocked; an approved status change request applies the status; sunset reminder selects products inside the window |
| Subscription guidance | Integration (`TestClient`) | Deprecated and retired → 409 with sunset date and replacement |
| Compliance DSL fix | Integration | A policy with `ASSIGN_TAG` assigns the tag; `REMOVE_TAG` removes it |
| Migration | Integration | `alembic upgrade head` succeeds; single head |

Prior art: `test_workflow_triggers_publish.py`, `test_data_product_routes.py`, existing compliance tests, and the `uc_tag_sync` tests from #737.

### Frontend Tests (Vitest + React Testing Library)

| Module | Test Type | What to Test |
|---|---|---|
| Deprecation dialog | Component | Requires a reason; validates sunset date; replacement picker excludes retired products |
| Deprecation banner | Component | Shows reason, sunset date and replacement link |
| Subscribe flow | Component | Shows the sunset date and replacement when a subscription is refused |

## Out of Scope

- **Reverse synchronization (Unity Catalog → Ontos).** Changing the lifecycle tag directly in Unity Catalog does not change the product status.
- **Automatic retirement on the sunset date.** Reaching `sunset_date` triggers reminders, not a status change.
- **Deprecating physical assets independently** of a product (asset-level lifecycle).
- **Marketplace (external) consumers.** Notifying Databricks Marketplace consumers belongs to #165.
- **Revoking existing access grants** on retirement. Grants stay until explicitly revoked.
- **New delivery mechanisms.** Lifecycle tags use the existing `uc_tag_sync` job; Direct Delivery is not extended.

## Further Notes

### Implementation phases

1. **Compliance DSL tag actions fix** — small, independent bug fix.
2. **Lifecycle fields** — model, migration, validation, export/import mapping, deprecation dialog.
3. **Lifecycle tag** — default tag sync entry and on-demand job run.
4. **Notices, approvals and subscription guidance** — notices, gate and request completion, reminder runner, subscribe errors, banner.
5. **Evidence** — audit details and manifest attestations (depends on the Signed Data Product Manifest).

### Open questions

- **Compliance Templates (#731):** should lifecycle fields instead be "system" fields provided by Compliance Templates (always present, not editable by admins), so that lifecycle and governance fields share one model?
- **Governed tags (#737):** should the lifecycle key use the governed-tag convention by default, and which key name do maintainers prefer (`ontos_lifecycle_status`, `lifecycle`, …)?
- Should certified deprecation gating also apply to contracts?
- Should subscribing to a deprecated product be allowed with an explicit acknowledgement (today it is refused)?
- Should the lifecycle default workflows start active on new installations, unlike other event-driven defaults (#989)?
- Should retirement automatically unpublish the product (`publication_scope = none`)?

### Relationship to existing PRDs and issues

- **PRD #86 (Unified Lifecycle Tracking)** — defines the status dimension this PRD builds on.
- **#731 / PRD #676 (Compliance Templates)** — typed governance fields and publish completeness gate; reused for the dialog inputs, with the field-model question above.
- **#737 (Domains ↔ Unity Catalog governed tags)** — the governed-tag convention and `uc_tag_sync` changes this PRD aligns with.
- **Signed Data Product Manifest PRD** — deprecation and retirement become attestations when manifests are enabled.
- **#421 (Governance Event Stream)** — `DataProductDeprecated` is a Phase 1 event; the default workflows can become subscribers once the stream exists.
- **#165 (Marketplace provider)** — external consumer notification on deprecation.
