# Data Product Lifecycle

A data product in Ontos is a versioned, governed bundle of related Databricks
(or other-platform) assets, exposed through one or more **Deliverables** (the
customer-facing name for output ports), depending on declared **Consumables**
(input ports), owned by a team, and optionally bound to one or more data
contracts. It implements the **Open Data Product Standard (ODPS) v1.0.0**
with Databricks-specific extensions.

In conversation you'll hear "Deliverable" and "Consumable". In the persisted
ODPS model these are `output_port` and `input_port`. Both vocabularies are
correct; the customer-facing names are primary.

## What a data product is {#what-is-a-data-product}

A data product groups tables, views, functions, models, dashboards,
notebooks, and jobs into a single cohesive unit with explicit ownership,
a lifecycle, and machine-readable input/output descriptions. The
DataProductsManager is the entry point for all lifecycle operations.

Core ODPS fields persisted on the product:

- `api_version` (e.g., `v1.0.0`)
- `kind` (default `DataProduct`)
- `status` — lifecycle state (see [Status state machine](#status-state-machine))
- `name`, `version`, `domain`, `tenant`
- `product_created_ts`
- Owner team reference (`owner_team_id`) and optional project (`project_id`)
- Description block (`purpose`, `limitations`, `usage`)
- Authoritative definitions (business definition links, tutorials, etc.)
- Custom properties (extensible key/value pairs)
- Input ports (Consumables), output ports (Deliverables), management ports
- Support channels and team metadata

Databricks extensions on the product:

- `consumer_principals` — typed list of identities authorized to consume
  output ports (see [Consumer principals](#consumer-principals)).
- `publication_scope` — visibility band for marketplace discovery
  (`none`, `domain`, `organization`, `external`).
- `certification_level` — optional ordinal pointing into the configured
  certification levels.
- Personal draft fields (`draft_owner_id`, `parent_product_id`,
  `base_name`, `change_summary`).

## Status state machine {#status-state-machine}

Data products use the unified `EntityStatus` enum. Valid statuses:

`draft`, `sandbox`, `proposed`, `under_review`, `approved`, `active`,
`deprecated`, `retired`.

Allowed transitions (`DATA_PRODUCT_TRANSITIONS`):

| From | To |
|---|---|
| draft | sandbox, proposed, deprecated |
| sandbox | draft, proposed, deprecated |
| proposed | draft, under_review, deprecated |
| under_review | draft, approved, deprecated |
| approved | active, draft, deprecated |
| active | deprecated |
| deprecated | retired, active |
| retired | (terminal) |

Notes:

- New products default to `draft` if no status is supplied at creation.
- A product can be published (made visible in the marketplace) only when
  the status is at least `approved`; publishing transitions it to
  `active` and stamps `published_at` / `published_by`.
- Certification is a **separate dimension** from status (it was removed
  from the status enum). Certification has its own fields and lifecycle.
- `retired` is terminal. A retired product cannot be revived.

## Ownership model {#ownership}

Three orthogonal layers of ownership apply to a data product:

1. **Domain** (`domain` field, free-text in ODPS — typically a Data
   Domain name). Selects which Data Governance Officer / Data Steward
   has oversight.
2. **Owner team** (`owner_team_id` → `teams.id`). The team is the
   durable organizational owner; team members inherit edit rights.
3. **Draft owner** (`draft_owner_id`). When set, the product is a
   personal draft visible only to that user (and elevated roles).
   Clearing `draft_owner_id` (the "commit" action) promotes the draft
   to team-visible status.

Authorization rules (enforced by DataProductsManager when checking edit
permissions):

- Admins can always edit.
- Team members inherit edit access through the owner team.
- A user whose email matches `draft_owner_id` can always edit (covers
  both personal drafts and single-user-owned products).
- Domain-scoped (`Filtered`) users can edit products in their domains.

## Deliverables (output ports) {#output-port}

A **Deliverable** describes a consumable surface of the data product. A
product typically has one or more Deliverables, each pointing at a
concrete asset and shipping through a specific delivery method.

Required ODPS fields on a Deliverable: `name`, `version`.

Optional fields:

- `description`, `port_type`
- `contract_id` — link to a data contract. **May be NULL by design**: a
  Deliverable can be declared without a contract during early lifecycle
  stages, and a contract can be attached later.
- `delivery_method_id` — reference to a configured delivery method (see
  [Delivery methods](#delivery-methods)).
- `asset_type`, `asset_identifier` — Databricks-side pointer (e.g.,
  `catalog.schema.table` for a UC table).
- `status` — independent port-level status string.
- `server` — JSON connection details.
- `contains_pii`, `auto_approve` — policy flags consumed by the
  agreement workflow.

A Deliverable can carry a list of **input contracts** (dependencies on
other contracts/versions) and an **SBOM** (software bill of materials)
block.

## Consumables (input ports) {#input-port}

A **Consumable** describes what the product reads. Unlike Deliverables,
**a `contract_id` is required** on every Consumable (per ODPS v1.0.0).
The identifier resolves to the contract version the product was built
against, making upstream changes diffable against the consumed schema.

Databricks extensions: `asset_type`, `asset_identifier`.

## Delivery methods {#delivery-methods}

A Deliverable references a configured Delivery Method. The named values
shipped with Ontos:

- **Table Access** — Consumer reads via Unity Catalog `SELECT`. The
  `grant_permissions` step in approval workflows wires the UC grants.
  This is the most common delivery method.
- **Serving Endpoint** — Consumer hits an HTTP serving endpoint (Mosaic
  AI Model Serving or equivalent). Access is brokered by serving
  endpoint configuration.
- **File Export** — Consumer pulls files from a configured location
  (volume, S3, ADLS, GCS). Export schedule is established when access is
  provisioned.
- **Streaming** — Consumer reads from a streaming source (Kafka, DLT,
  etc.). Streaming-specific connection details ride on the Deliverable.

The list is configurable from Settings → Delivery Methods, so a
deployment can extend it with org-specific delivery patterns (Postgres
shares, JDBC handoffs, dbt project handoffs, etc.).

## Management ports {#management-port}

Management ports expose administrative endpoints for the product:
discovery, observability, control, dictionary. Required fields are
`name` and `content` (one of `discoverability`, `observability`,
`control`, `dictionary`). Optional fields: `port_type` (default
`rest`), `url`, `channel`, `description`.

## Consumer principals {#consumer-principals}

`consumer_principals` is a JSON list of typed identity references
describing who is allowed to consume the product's Deliverables. Each
entry has a `type` and a `value`:

- `type: "group"` (default) — a Databricks workspace/account group
  display name.
- `type: "service_principal"` — an SP `applicationId`.
- `type: "role"`, `type: "scope"`, etc. — reserved for future identity
  methods.

The agreement workflow propagates the resolved consumer principals into
the workflow execution context so that `grant_permissions` steps and
webhook templates can reference `${entity.consumer_principals}` when
granting Unity Catalog privileges.

Two operational rules here:

- The Ontos app service principal needs **`MANAGE`** on each UC
  securable it grants on. `ALL_PRIVILEGES` is **not** sufficient.
- UC accepts only **account-level groups**; workspace-only groups
  will be rejected even if they resolve in Ontos's identity layer.

## Semantic links and tags {#semantic-links-tags}

A data product can carry:

- **Semantic links** — references to ontology concepts (concept IRIs)
  via the shared `entity_semantic_links` table. This is how a product
  participates in the knowledge graph and glossary navigation. See
  [Semantic Link](ontology-and-knowledge-graph.md#three-tier-linking).
- **Tags** — namespaced tag references via the shared tag system. See
  [Tag](entities-glossary.md#tag) in the glossary.
- **Custom properties** — ODPS-native, free-form `property`/`value`
  pairs at the product level.

## Quality measurement attachment {#quality-attachment}

A data product does not own quality checks directly. Quality checks
live on the data contract bound to a Deliverable. The product's Quality
panel is a rollup over the contracts the product binds — see
[Data Quality](data-quality.md#measurements-and-rollup).

Subscribing to a product implicitly registers the consumer for
compliance alerts when the bound contract's quality checks fail.

## Publication and subscription {#publication-subscription}

- `publication_scope` controls marketplace visibility: `none` (default),
  `domain`, `organization`, `external`.
- The legacy `published` boolean column is retained for backward DB
  compatibility but is superseded by `publication_scope`.
- Consumers can subscribe to a product (`DataProductSubscriptionDb`),
  opting into ITSM notifications for deprecations, new versions, and
  compliance violations. Subscriptions support **subscribe-on-behalf-of**
  for groups and service principals (`on_behalf_of_type`,
  `on_behalf_of_value`).

## Versioning {#versioning}

Versioning is explicit: each version is its own product row. Versions of
the same product are grouped by a stable family identifier — historically
`base_name` paired with the `parent_product_id` parent-walk, and in the
current Ontos version moving toward a canonical `version_family_id`
column that survives renames and is propagated through every clone path.
Either way, the lifecycle invariant is the same: a row per version,
linked to its predecessors, with a separate `change_summary` capturing
the human-readable diff. There is no automatic version promotion —
version transitions are author-driven.

List views collapse by family by default (one row per family, showing
the most-relevant version for the caller's role) with an option to
expand and see every version individually. Detail views surface a
version navigator so authors and consumers can move between versions
of the same product without losing context.

## Common questions {#common-questions}

**"What is the difference between Deliverable and output port?"**

Same thing. Deliverable is the customer-facing name we use in
conversation, in the UI, and in the marketplace; output port is the
ODPS-spec label used in the persisted model and in ODPS exports. Same
for Consumable vs input port. Use whichever name your audience uses.

**"My Deliverable has a NULL contract — is that allowed?"**

Yes. Deliverables can be declared without a contract during early
lifecycle stages (draft, sandbox, proposed). You can attach a contract
later. Consumables, by contrast, are required to reference a contract
version per ODPS — this is what makes upstream changes diffable against
what you consumed.

**"What does `auto_approve` on a Deliverable do?"**

It is a policy flag the agreement workflow reads. When set, the
subscribe / request-access workflow short-circuits the approval gate
and proceeds directly to `grant_permissions`. Use sparingly — it's
appropriate for low-sensitivity, public-data products where governance
overhead has no upside.

**"How do I move my product from draft to proposed?"**

Click the status action on the detail page. The transition fires the
`on_request_status_change` process trigger (if a workflow is matched)
or the inline status update path otherwise. The transition itself only
needs `data-products:READ_WRITE` and ownership; an approval gate, if
configured, will pause for the approver before the status flips.

**"Why don't I see this product in the marketplace?"**

Three usual causes. (1) `publication_scope` is `none` (default for new
products). (2) Status is not yet `active`. (3) Publication scope is
`domain` and the consumer isn't in the domain. Look at status and
publication_scope on the product detail page.

**"What does publishing a product do — does it grant permissions
automatically?"**

Publishing transitions status to `active` and makes the product
visible in the marketplace. It does **not** by itself grant UC
permissions to consumers. Permissions get granted when a consumer
subscribes and the subscribe workflow runs its `grant_permissions`
step. The publication step is a *visibility* operation; the
subscription step is the *access* operation. They are deliberately
separate.

**"My product has 4 deliverables — does each one need its own
contract?"**

You can do that, or you can let one contract serve several
Deliverables (the contract's schema can describe the union of what the
Deliverables expose). Most teams start with one contract per
Deliverable for clarity and only consolidate when they have repeated
patterns.

## Cross-references {#cross-references}

- [Data Contract](data-contract-lifecycle.md#what-is-a-contract) for
  what the bound contract carries
- [Approval workflow](agreement-workflow.md#approval-roles) for how
  subscribe / publish gates work
- [Data Quality rollup](data-quality.md#measurements-and-rollup) for
  the Quality panel
- [Semantic links](ontology-and-knowledge-graph.md#three-tier-linking)
  for concept assignment
- [Bottom-up flow](end-to-end-flows.md#flow-a-bottom-up) for the
  end-to-end producer journey

_Last verified against codebase: 2026-05-28_
