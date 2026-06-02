# Data Contract Lifecycle

A data contract in Ontos is the technical and semantic agreement that a
data product's Deliverable implements — schema, quality expectations, SLAs,
server endpoints, support channels, pricing. Ontos implements the **Open
Data Contract Standard (ODCS) v3.1.0**.

The model customers reach for: *Ontos is the lifecycle manager of data
contracts. Create v2, inform users about the changes from v1. Ontos can diff
and include the list of changes.* The two operational ideas underneath that
sentence are **editor-of-record** and **indirect delivery**.

## What a contract is {#what-is-a-contract}

A data contract is the technical and semantic agreement attached to a data
product's Deliverable. The DataContractsManager owns the lifecycle.

Required identity fields (ODCS):

- `kind` (default `DataContract`)
- `api_version` (default `v3.1.0`)
- `name`, `version` — semver-style version string
- `status` — lifecycle state (see [Status state machine](#status-state-machine))

Optional ODCS top-level fields:

- `tenant`, `data_product` (free-text product name)
- `domain_id` — link to a Data Domain
- Description block (`usage`, `purpose`, `limitations`)
- `sla_default_element`, `contract_created_ts`

Databricks extensions: `owner_team_id`, `project_id`, certification fields,
publication scope, personal draft fields, and parent/base-name links for
explicit versioning.

## Editor of record {#editor-of-record}

The default mental model: **Ontos is the editor of record for the
contract**. You draft, edit, propose, review, and version the contract
in Ontos. The contract has a stable DB row, an immutable agreement
trail (when approval workflows are involved), and a diff view between
versions.

The alternative: customers who already have YAML contracts in their
workspace repo can run **indirect delivery via volume** — Ontos pushes
the canonical YAML representation into a configured Databricks Volume,
where the workspace deployment pipelines pick it up. The seam is
deliberate:

- The DB is the editor of record.
- The Volume is the deployment surface.

If a team edits the YAML in their workspace and then re-imports it,
they're choosing to make the workspace the editor of record — at which
point Ontos becomes the observer. Pick one direction and stay there
per contract; round-tripping leads to drift.

This pattern is exactly the answer to the customer question: *"Switching
contract versions >>> trigger a job and notify people."* Ontos owns the
event of v1 → v2 (with diff + approval gate + notification fan-out);
the volume / job system owns the *deployment* of the new YAML.

## Status state machine {#status-state-machine}

Contracts use the unified `EntityStatus` enum but support a slightly
smaller set than data products (no `sandbox`):

`draft`, `proposed`, `under_review`, `approved`, `active`, `deprecated`,
`retired`.

Allowed transitions (`DATA_CONTRACT_TRANSITIONS`):

| From | To |
|---|---|
| draft | proposed, deprecated |
| proposed | draft, under_review, deprecated |
| under_review | draft, approved, deprecated |
| approved | active, draft, deprecated |
| active | deprecated |
| deprecated | retired, active |
| retired | (terminal) |

New contracts default to `draft`. Publishing (in the marketplace sense)
is governed by `publication_scope`, distinct from status.

## Contracts-First vs Products-First {#contracts-vs-products-first}

Two equally-supported workflow orderings. The platform doesn't favor one;
the choice is a team-culture choice.

**Contracts-First.** The contract is drafted before product assets are
linked. Producer and consumer iterate on schema, quality expectations,
and SLAs in a shared design. The Steward approves the contract first.
The Producer then builds the product to satisfy the contract. Lower
risk of late surprises; higher upfront design cost.

**Products-First.** The product is composed with assets first. Contracts
are attached to Deliverables later, possibly per Deliverable. The
contract is drafted to reflect what's already there. Faster initial
delivery; risk that consumer needs surface only after the product is
half-built.

Both flows pass through the same status state machine. Stewards in
Contracts-First gate at contract approval; in Products-First, they gate
at product certification (and at contract approval if the contract is
formal).

## Schema objects and properties {#schema-objects}

A contract's schema is a tree:

- **Schema object** (`SchemaObjectDb`) — table-equivalent. Has `name`,
  `logical_type` (default `object`), optional `physical_name`,
  `physical_type`, `business_name`, `description`, `tags`,
  `data_granularity_description`.
- **Schema property** (`SchemaPropertyDb`) — column-equivalent. Has
  `name`, `logical_type`, `physical_type`, flags (`required`, `unique`,
  `primary_key`, `partitioned`, `critical_data_element`), and rich
  transformation metadata (`transform_source_objects`,
  `transform_logic`, `transform_description`). Properties may nest via
  `parent_property_id` for struct/array types.

Properties can carry ODCS classification (`classification`),
encrypted-name hints, examples, and a JSON blob of logical-type-specific
options (`logical_type_options_json`).

Each schema object and property is itself an entity that can carry
semantic links — see
[Three-tier linking](ontology-and-knowledge-graph.md#three-tier-linking).

## Quality checks {#quality-checks}

A `DataQualityCheckDb` row is a **check definition** attached to a
schema object (or a specific property). Definitions are *not*
execution results — execution and historical scoring are tracked
separately via `QualityItemDb` and the compliance/notifications
systems. The full story is in
[data-quality.md](data-quality.md#contract-check-definitions).

A check has:

- `level` — `object` (table-wide) or `property` (column-specific).
- `dimension` — ODCS quality dimension: `accuracy`, `completeness`,
  `conformity`, `consistency`, `coverage`, `timeliness`, `uniqueness`.
- `business_impact` — `operational` or `regulatory`.
- `severity` — `info`, `warning`, `error`.
- `type` — `library` (named rule), `text`, `sql` (free `query`), or
  `custom` (with `engine` and `implementation`).
- A family of comparator fields (`must_be`, `must_not_be`, `must_be_gt`,
  `must_be_between_min`/`max`, etc.) for declarative thresholds.

Profiling runs (`DataProfilingRunDb`) record discovery/profiling
activity (DQX, LLM-suggested, manual) and produce
`SuggestedQualityCheckDb` rows that can be accepted or rejected and
then promoted into real checks.

## Servers and environments {#servers}

A contract's `servers` block lists the environments where the contract
applies. Each `DataContractServerDb` row carries `type` (required),
`environment`, optional `description`, and a `properties` collection of
key/value pairs for connection details. Servers support ODCS v3.1.0
stable IDs so external referrers can point at a specific server entry
across version edits.

## Contract roles {#contract-roles}

A contract declares its own access roles (`DataContractRoleDb`)
independent of Ontos's RBAC roles. Each entry names a role with
`access`, `first_level_approvers`, `second_level_approvers`, and
optional custom properties. These represent the **access role** layer of
the contract — the business statement of who can read or write the
underlying data — and feed into the agreement workflow as configurable
approver groups.

## SLAs and support {#sla-support}

- `DataContractSlaPropertyDb` — typed SLA entries with `property`,
  `value`, `unit`, `element`, and `driver`. Supports ODCS SLA
  semantics.
- `DataContractSupportDb` — communication channels for support
  (`channel`, `url`, `tool`, `scope`, `invitation_url`).
- `DataContractPricingDb` — single-row pricing block
  (`price_amount`, `price_currency`, `price_unit`).

## Relationships {#contract-relationships}

ODCS v3.1.0 schema-level and property-level relationships (foreign
keys) are stored in `data_contract_schema_object_relationships` and
`data_contract_schema_property_relationships`. Relationship type
defaults to `foreignKey`; `from_value` / `to_value` are JSON-serialized
to allow single-string or array references.

## Authoritative definitions {#contract-auth-defs}

Contracts, schema objects, and individual properties can each link to
authoritative external definitions (`url` + `type`). This is how a
contract binds itself to a business term in the glossary, a
transformation specification, or a regulatory reference.

## Publication and certification {#publication-certification}

`publication_scope` (`none`/`domain`/`organization`/`external`)
replaces the legacy `published` boolean for marketplace visibility.
Certification fields (`certification_level`,
`inherited_certification_level`, `certified_at`, `certified_by`,
`certification_expires_at`, `certification_notes`) operate
independently from status.

## Relationship to data products {#relationship-to-products}

A contract is bound to a data product through a **Deliverable** of the
product (`OutputPortDb.contract_id`). A single contract may serve
multiple Deliverables — possibly across multiple products. The
product's Consumables carry contract references for upstream
dependencies, with the contract version pinned at integration time.
Subscribers to a product receive compliance alerts when the bound
contract's quality checks fail.

## Versioning and diffing {#versioning-and-diffing}

Versions are explicit rows grouped by a stable family identifier —
historically `base_name` paired with the `parent_contract_id`
parent-walk, and in the current Ontos version moving toward a canonical
`version_family_id` column that survives renames. The customer-voice
framing — *Create v2, inform users about the changes from v1, Ontos can
diff and include the list of changes* — maps onto two Ontos behaviors:

1. The diff view between two contract versions presents schema, quality
   check, SLA, and server changes side-by-side.
2. The contract subscription / dependency graph drives notification
   fan-out when a new version is approved. Subscribers to the binding
   product (and consumers of dependent products) get notifications;
   the workflow can also fire a webhook to ITSM / Slack / email.

List views collapse by family by default (one row per family, the
most-relevant version surfaced according to caller role) with a toggle
to expand and see every version. The detail view's version navigator
lets authors and consumers move across versions without losing context.

If you also push the YAML to a volume (Indirect delivery — see
[Delivery and Propagation](delivery-and-propagation.md#indirect-mode)),
a workspace job picks up the new version and applies it — but the diff
and the notification fan-out happens in Ontos.

## Common questions {#common-questions}

**"Does edits to the YAML in my workspace flow back into Ontos?"**

In the current Ontos version: not automatically. Ontos is the editor
of record; the workspace volume is the deployment surface. If your
team edits the YAML in the workspace, you're implicitly choosing the
workspace as the editor of record — re-importing the edited YAML into
Ontos is possible, but it overwrites whatever Ontos held. Pick one
direction and stick to it for a given contract.

**"What does 'switching contract versions' do — does it trigger a
job?"**

Switching to a new active version transitions the previous version to
`deprecated`, transitions the new version to `active`, and fires the
configured event-driven workflows (e.g., `on_status_change`). Those
workflows are how customers wire downstream side effects: trigger a
deployment job, fan out notifications to subscribers, post to ITSM,
push the YAML to a volume. Ontos owns the event; the workflows you
configure own the side effects.

**"Where do I see what changed between v1 and v2?"**

The contract detail page has a Compare action that selects another
version of the same `base_name` and renders a structured diff. The
diff covers schema additions / removals / type changes, quality check
adds / removes / threshold changes, SLA changes, and server changes.

**"Can a single contract cover multiple Deliverables?"**

Yes. One contract can be bound to multiple Deliverables, possibly
across multiple products. The reverse — multiple contracts on a
single Deliverable — is not the model; a Deliverable has at most one
`contract_id`.

**"My contract has 12 quality checks defined but the product's
Quality panel says 0% — why?"**

Quality check definitions are not measurements. The contract holds
the design intent; the product's Quality panel reads
`QualityItemDb` measurements (per dimension, per source). If no
profiling run, no dbt run, no DQX run, and no manual measurement has
written a `QualityItemDb` row yet, there's nothing to roll up. See
[Two systems at a glance](data-quality.md#two-systems).

**"Why are quality checks defined per schema property and not just
per schema object?"**

ODCS allows both: object-level checks (the whole table) and
property-level checks (one column). Most checks land at the property
level because that's where the granularity is — completeness of
`customer_id`, conformity of `country_code` to ISO 3166. Object-level
checks cover row-count expectations, freshness of the latest
partition, and other table-wide invariants.

## Cross-references {#cross-references}

- [Data Quality](data-quality.md) — definitions vs measurements vs
  DQX
- [Data Product](data-product-lifecycle.md#what-is-a-data-product) and
  [Deliverable](data-product-lifecycle.md#output-port)
- [Approval workflow](agreement-workflow.md#approval-roles) for
  contract review approval gates
- [Semantic Link](ontology-and-knowledge-graph.md#three-tier-linking)
  for concept assignment at schema and property level
- [Bottom-up flow Step 3](end-to-end-flows.md#step-a-3) and the
  Contracts-First vs Products-First decision

_Last verified against codebase: 2026-05-28_
