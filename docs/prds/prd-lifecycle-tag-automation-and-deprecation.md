# PRD: Lifecycle Tag Automation and Deprecation Propagation

## Problem Statement

Ontos models lifecycle well — Data Products move through `draft → sandbox/proposed → under_review → approved → active → deprecated → retired` (`models/lifecycle.py`) — but deprecating a product is today a status change and nothing more. Everything that should happen *around* a deprecation is left to people.

Concretely:

- **No deprecation metadata.** There is no sunset date, no replacement product, no reason and no deprecation timestamp on Data Products or Data Contracts. Consumers learn that something is deprecated, but not until when, why, or what to use instead.
- **Subscribers are not told.** `entity_subscriptions_manager` lets users subscribe to a product, but transitioning a product to `deprecated` or `retired` sends no notification to its subscribers.
- **New subscriptions are not gated.** `DataProductsManager.subscribe` does not check the product status, so a user can subscribe to a deprecated — or retired — product without warning or approval.
- **Lifecycle reaches Unity Catalog only by accident of configuration.** The `uc_tag_sync` job can already write `{PRODUCT.STATUS}` or `{CONTRACT.STATUS}` as a Unity Catalog tag through `tag_sync_configs`, but no default entry does so, the job runs on a 4-hour schedule, and a deprecation does not trigger a run. Direct Delivery does not apply tag changes at all (only `GRANT`/`REVOKE`). Analysts querying a table directly therefore have no reliable, timely signal that its product is being retired.
- **The declarative path is broken.** The Compliance DSL advertises `ASSIGN_TAG` / `REMOVE_TAG`, but `ComplianceManager` builds the `ActionContext` without a tag manager, so these actions currently fail with "Tag manager not available".
- **Certified products can be deprecated without review.** There is no default gate requiring approval before a certified product is deprecated.
- **No durable evidence.** Who deprecated a product, why, and with what replacement is only partially visible in the change log and not packaged as evidence (see the Signed Data Product Manifest PRD).

The building blocks exist — `on_status_change` / `before_status_change` / `scheduled` workflow triggers, notification steps, entity subscriptions, the configurable `uc_tag_sync` job and `JobsManager.run_job` — but there is no standard, end-to-end deprecation behavior.

## Solution

Ship a **standard deprecation lifecycle** for Data Products (and the same fields for Data Contracts), assembled from existing primitives and aligned with work in flight:

1. **Deprecation vocabulary** — `deprecation_reason`, `sunset_date`, `replacement_product_id` (contracts: `replacement_contract_id`) and `deprecated_at`, captured by a deprecation dialog and required when moving to `deprecated`. Stored as first-class lifecycle fields (see *Data model* for why not as Compliance Template fields, #731).
2. **Lifecycle tag in Unity Catalog via `uc_tag_sync`** — a default `tag_sync_configs` entry that writes the product status to the physical assets of its output ports (`ontos_lifecycle_status = {PRODUCT.STATUS}`), following the governed-tag conventions introduced for domains in #737 where governed tags are enabled. No new delivery mechanism.
3. **Timely propagation** — after a transition to `deprecated`, `retired` or back to `active`, Ontos requests an on-demand `uc_tag_sync` run through `JobsManager.run_job` when the job is installed; otherwise the next scheduled run applies the tag.
4. **Default deprecation workflows** — shipped (editable, not deletable) workflows on `on_status_change` that notify owners and subscribers, a `before_status_change` gate that requires approval to deprecate a **certified** product, and a `scheduled` sunset reminder.
5. **Subscription gating** — subscribing to a `deprecated` product requires an explicit acknowledgement (and shows the replacement); subscribing to a `retired` product is rejected.
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
8. As a Data Consumer, I want a clear warning and an acknowledgement step before subscribing to a deprecated product, so that I do not build on something that is going away.
9. As a Data Consumer, I want subscribing to a retired product to be blocked, with a pointer to its replacement.

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

### Default workflows

- **Deprecation notice** (`on_status_change`, to `deprecated`): notify owners, business owners and all subscribers with reason, sunset date and replacement.
- **Retirement notice** (`on_status_change`, to `retired`): notify subscribers.
- **Certified deprecation gate** (`before_status_change`, to `deprecated`, when `certification_level` is set): require approval by a role with `data-products` Admin (default: Data Governance Officer).
- **Sunset reminder** (`scheduled`, daily): notify subscribers of products whose `sunset_date` is within a configurable window (default 14 days).
- Shipped as default workflows (editable, duplicable, not deletable), consistent with the default workflow catalog in `src/docs/USER-GUIDE.md`. Notification texts can reference the new fields through the workflow template variables.

### Subscription gating

- `DataProductsManager.subscribe` checks status: `retired` → `409` with the replacement id; `deprecated` → requires `acknowledge_deprecation=true` in the request, otherwise `409` with sunset date and replacement.
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
4. **Default workflows** — deprecation notice, retirement notice, certified deprecation gate, sunset reminder.
5. **Subscription gating** — manager checks, API contract, UI banner and acknowledgement.
6. **Evidence** — audit details and manifest attestations.

## Testing Decisions

### Backend Tests (pytest)

| Module | Test Type | What to Test |
|---|---|---|
| Lifecycle fields | Unit | Deprecation requires a reason; past sunset dates rejected; replacement must exist and not be retired; reactivation clears fields; ODPS/ODCS round-trip keeps the fields |
| Lifecycle tag | Unit | `build_desired_for_dataset` produces `ontos_lifecycle_status=<status>` from the default config (stubbed pyspark, following the `uc_tag_sync` test approach introduced in #737); transition hook requests one debounced job run; no run requested when the job is not installed |
| Default workflows | Integration | Deprecation notifies owners and subscribers with reason/sunset/replacement; certified deprecation is gated until approved; sunset reminder selects products inside the window |
| Subscription gating | Integration (`TestClient`) | Retired → 409; deprecated without acknowledgement → 409; deprecated with acknowledgement → subscribed |
| Compliance DSL fix | Integration | A policy with `ASSIGN_TAG` assigns the tag; `REMOVE_TAG` removes it |
| Migration | Integration | `alembic upgrade head` succeeds; single head |

Prior art: `test_workflow_triggers_publish.py`, `test_data_product_routes.py`, existing compliance tests, and the `uc_tag_sync` tests from #737.

### Frontend Tests (Vitest + React Testing Library)

| Module | Test Type | What to Test |
|---|---|---|
| Deprecation dialog | Component | Requires a reason; validates sunset date; replacement picker excludes retired products |
| Deprecation banner | Component | Shows reason, sunset date and replacement link |
| Subscribe flow | Component | Shows acknowledgement for deprecated products; blocks retired products |

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
4. **Default workflows and subscription gating** — notices, gate, reminder, subscribe checks, banner.
5. **Evidence** — audit details and manifest attestations (depends on the Signed Data Product Manifest).

### Open questions

- **Compliance Templates (#731):** should lifecycle fields instead be "system" fields provided by Compliance Templates (always present, not editable by admins), so that lifecycle and governance fields share one model?
- **Governed tags (#737):** should the lifecycle key use the governed-tag convention by default, and which key name do maintainers prefer (`ontos_lifecycle_status`, `lifecycle`, …)?
- Should certified deprecation gating also apply to contracts?
- Should retirement automatically unpublish the product (`publication_scope = none`)?

### Relationship to existing PRDs and issues

- **PRD #86 (Unified Lifecycle Tracking)** — defines the status dimension this PRD builds on.
- **#731 / PRD #676 (Compliance Templates)** — typed governance fields and publish completeness gate; reused for the dialog inputs, with the field-model question above.
- **#737 (Domains ↔ Unity Catalog governed tags)** — the governed-tag convention and `uc_tag_sync` changes this PRD aligns with.
- **Signed Data Product Manifest PRD** — deprecation and retirement become attestations when manifests are enabled.
- **#421 (Governance Event Stream)** — `DataProductDeprecated` is a Phase 1 event; the default workflows can become subscribers once the stream exists.
- **#165 (Marketplace provider)** — external consumer notification on deprecation.
