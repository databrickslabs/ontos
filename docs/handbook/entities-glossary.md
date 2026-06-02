# Entities Glossary

One-paragraph definitions of every first-class entity in Ontos. Cross-links
go to the appropriate lifecycle, concept, or role document for the longer
story.

## Organizational hierarchy {#organizational}

- **Domain** {#domain} — A business area that owns data assets (e.g.,
  "Sales", "Supply Chain"). Domains have an optional parent (`parent_id`)
  to express a hierarchy. They are the primary scoping unit for the
  `Filtered` access level and the typical anchor for data products.
  Persisted in `data_domains`.
- **Team** {#team} — A durable group of users who collectively own work.
  Stored in `teams` with `team_members` for membership. Teams can be
  the owner of a data product (`owner_team_id`) or contract. A team
  member may carry an `app_role_override` that elevates that user's
  effective Ontos role for the lifetime of the membership.
- **Project** {#project} — A bounded initiative under a team or domain.
  Projects scope data products and contracts (`project_id`). Workflows
  can also be scoped to projects via `ScopeType.PROJECT`.

## Data assets {#data-assets}

- **Data Product** {#data-product} — A versioned, ODPS-conformant unit
  of related assets exposed through Deliverables, owned by a team,
  optionally bound to a project and domain. See
  [data-product-lifecycle.md](data-product-lifecycle.md#what-is-a-data-product).
- **Data Contract** {#data-contract} — An ODCS v3.1.0 specification of
  an interface — schema, quality, SLA, servers, support. A data
  contract is attached to a data product via Deliverables (and
  referenced by Consumables). See
  [data-contract-lifecycle.md](data-contract-lifecycle.md#what-is-a-contract).
- **Deliverable / Output Port** {#output-port} — A consumable surface
  of a data product. *Deliverable* is the customer-facing name;
  *output port* is the ODPS-spec persisted-model label. May or may not
  have a `contract_id` (NULL is allowed). May carry a delivery method
  and an SBOM. See
  [data-product-lifecycle.md](data-product-lifecycle.md#output-port).
- **Consumable / Input Port** {#input-port} — An upstream dependency
  of a data product. *Consumable* is the customer-facing name;
  *input port* is the ODPS-spec label. `contract_id` is required (ODPS
  rule). See
  [data-product-lifecycle.md](data-product-lifecycle.md#input-port).
- **Management Port** {#management-port} — An administrative endpoint
  of a data product (discoverability, observability, control,
  dictionary).
- **Delivery Method** {#delivery-method} — A configured way of
  delivering data from a Deliverable: Table Access (UC SELECT),
  Serving Endpoint (HTTP serving), File Export (volume / object store),
  Streaming (Kafka / DLT). Configurable from Settings → Delivery
  Methods. See
  [data-product-lifecycle.md](data-product-lifecycle.md#delivery-methods).
- **Schema Object** {#schema-object} — A table-equivalent entry inside
  a contract's schema. Carries logical/physical type, granularity,
  tags, quality checks. See
  [data-contract-lifecycle.md](data-contract-lifecycle.md#schema-objects).
- **Schema Property** {#schema-property} — A column-equivalent entry
  under a schema object. Carries type, flags (`required`, `unique`,
  `primary_key`, `partitioned`, `critical_data_element`),
  transformation metadata, and may nest via `parent_property_id`.
- **Quality Check** {#quality-check} — A check **definition** attached
  to a schema object or property. Not a result. Has a dimension,
  severity, business impact, type (`library`/`text`/`sql`/`custom`),
  and a family of declarative comparators. See
  [data-contract-lifecycle.md](data-contract-lifecycle.md#quality-checks).
- **Quality Item** {#quality-item} — A *measurement* row scoped to an
  entity (`data_product`, `data_contract`, `asset`, `data_domain`).
  Carries `score_percent`, `checks_passed`, `checks_total`,
  `measured_at`, `dimension`, and a `source` enum (`manual` / `dbt` /
  `dqx` / `great_expectations` / `soda` / `external`). Rolled up via
  `QualityManager.aggregate_for_product`. See
  [data-quality.md](data-quality.md#measurements-and-rollup).
- **Asset** {#asset} — A persisted reference to a governed "thing"
  (table, view, dashboard, model, etc.) stored in the database with a
  typed `asset_type_id` and an optional `domain_id`. Distinct from the
  connector-level `UnifiedAssetType` enum, which classifies
  cross-platform asset categories at the integration boundary.
- **Asset Type** {#asset-type} — The persisted classification of an
  asset, driven by the ontology TTL file at startup. Carries category,
  icon, required/optional metadata schemas, allowed relationships. See
  [ontology-and-knowledge-graph.md](ontology-and-knowledge-graph.md#prescriptive-principle).

## Agreements and workflows {#workflow-entities}

- **Agreement** {#agreement} — The *immutable* record of a completed
  approval workflow, including the workflow snapshot and per-step
  results. Never modified after persistence. See
  [agreement-workflow.md](agreement-workflow.md#what-is-an-agreement).
- **Approval Gate** {#approval-gate} — A first-class concept: a moment
  in an entity's lifecycle where a configured approver must sign off
  before the next state. Used at Contract Approval, Sandbox Ready,
  Product Certified, Product Active. Implemented as an approval
  workflow matched by trigger type. See
  [agreement-workflow.md](agreement-workflow.md#approval-gates).
- **Workflow** {#workflow} — A *definition* with a trigger, scope,
  type (`process` or `approval`), and an ordered list of steps. Stored
  in `process_workflows` with `workflow_steps`. Different from a
  Workflow Execution or a Wizard Session.
- **Workflow Execution** {#workflow-execution} — A single *runtime*
  invocation of a workflow. Tracks status (`pending` / `running` /
  `paused` / `succeeded` / `failed` / `cancelled`) and current step.
  See
  [agreement-workflow.md](agreement-workflow.md#execution-state-machine).
- **Workflow Step** {#workflow-step} — One node in a workflow,
  identified by a slug `step_id`. Has a `step_type` (validation,
  approval, user_action, webhook, grant_permissions, etc.), a JSON
  `config`, and optional `on_pass` / `on_fail` branching targets.
- **Wizard Session** {#wizard-session} — The user-facing *in-flight*
  state of an approval workflow. Holds the snapshotted workflow
  definition (so later edits don't change what's being signed) and
  per-step user inputs collected so far. Resolves to an Agreement on
  completion. See
  [agreement-workflow.md](agreement-workflow.md#three-concepts).

## Semantics and tagging {#semantics-tagging}

- **Ontology** {#ontology} — The *source artifact*: a `.ttl` / `.owl`
  / `.rdf` / `.nt` file authored externally (Protégé, TopBraid, or a
  text editor). Declares classes, data properties, object properties,
  optional SHACL shapes. Distinct from the runtime knowledge graph
  built from it. See
  [ontology-and-knowledge-graph.md](ontology-and-knowledge-graph.md#four-words).
- **Knowledge Graph** {#knowledge-graph} — The *runtime* structure:
  an rdflib ConjunctiveGraph rebuilt from the union of enabled
  ontologies, stored as triples in the `rdf_triples` table. Queried
  via SPARQL at `/api/semantic-models/query`. See
  [ontology-and-knowledge-graph.md](ontology-and-knowledge-graph.md#runtime-graph).
- **Concept / Ontology Concept** {#ontology-concept} — A node in the
  knowledge graph, identified by an IRI (e.g.,
  `https://example.com/ontology/Customer`). RDF-native; not a
  separate table. Concepts have a status aligned with the unified
  `EntityStatus`. Distinct from a *Glossary Term* (which is a UX
  surface for a published concept).
- **Concept IRI** {#concept-iri} — The W3C-style identifier of a
  concept. Used as the link target in semantic links.
- **Semantic Link** {#semantic-link} — A row in
  `entity_semantic_links` that pins an entity (`data_domain` /
  `data_product` / `data_contract` / `data_contract_schema` /
  `dataset` / `asset` / `uc_catalog` / `uc_schema` / `uc_table` /
  `uc_column`) to a concept IRI with an optional human-readable
  label. Three-tier on contracts: contract-level, schema-level,
  property-level. See
  [ontology-and-knowledge-graph.md](ontology-and-knowledge-graph.md#three-tier-linking).
- **Business Glossary Term / Glossary Term** {#glossary-term} — The
  UX presentation of a published concept that has been added to a
  glossary collection (`urn:glossary:` context). There is **no
  separate glossary terms table** — a "term" is a concept plus its
  glossary-collection membership. Distinct from the underlying
  *concept*. See
  [ontology-and-knowledge-graph.md](ontology-and-knowledge-graph.md#glossary-as-view).
- **Glossary Collection** {#glossary-collection} — A knowledge
  collection with `collection_type=glossary`. Hosts the concepts
  presented as terms. Has a name, description, domain scope, and
  owner.
- **Tag** {#tag} — A typed label attached to an entity. Tags live
  inside a namespace and may carry their own status and permissions.
- **Tag Namespace** {#tag-namespace} — A grouping of tags under a
  name (e.g., `pii`, `domain`). Permissions can be configured per
  namespace via `tag_namespace_permissions`.

## Identity and access {#identity-access}

- **User** {#user} — A caller identified by email and the groups
  Ontos resolves for them at request time. See
  [roles-and-rbac.md](roles-and-rbac.md#identity-resolution).
- **Role** {#role} — An Ontos role: a named bundle of feature →
  access-level mappings, with a list of `assigned_groups`. The seeded
  roles are Admin, Data Governance Officer, Data Steward, Data
  Producer, Data Consumer, Security Officer. See
  [roles-and-rbac.md](roles-and-rbac.md#built-in-roles).
- **Feature** {#feature} — A unit of UI/API surface (e.g.,
  `data-products`, `data-contracts`, `settings-roles`). Defined in
  the `APP_FEATURES` map with a display name, allowed access levels,
  and a sidebar group (`Discover`, `Build`, `Govern`, `Deploy`,
  `Settings`, `Other`).
- **Permission** {#permission} — A `feature_id : access_level` pair
  that gates a user's actions on a feature. See
  [roles-and-rbac.md](roles-and-rbac.md#permission-model).
- **Access Level** {#access-level} — One of `None`, `Read-only`,
  `Filtered`, `Read/Write`, `Full`, `Admin`. Applied per feature. See
  [roles-and-rbac.md](roles-and-rbac.md#access-levels).
- **Consumer Principal** {#consumer-principal} — A typed identity
  reference on a data product describing who may consume it. Default
  type is `group`; other supported types include `service_principal`.
  Resolved into UC grants by the `grant_permissions` step. See
  [data-product-lifecycle.md](data-product-lifecycle.md#consumer-principals).
- **Workspace Admin** {#workspace-admin} — A user who is a member of
  a Databricks group listed in `APP_ADMIN_DEFAULT_GROUPS`. Granted
  admin treatment for cascade-bypass checks **independent of the
  Ontos role system**. See
  [roles-and-rbac.md](roles-and-rbac.md#workspace-admin-shortcut).
- **Ontos Admin** {#ontos-admin} — A user resolved (via group or
  email-as-group fallback) to an Ontos role that holds the `Admin`
  level on the `Admin` row (or on the relevant feature). Distinct
  from Workspace Admin: a user can be one without the other.
- **Subscription** {#subscription} — A consumer's registration to a
  data product, optionally on-behalf-of a group or service principal.
  Drives ITSM notifications when the product or its bound contract
  changes.

## People (not seeded roles) {#people-personas}

- **Knowledge Engineer / Data Architect** {#knowledge-engineer} —
  Not a seeded Ontos role; the persona behind ontology authoring.
  Authors the ontology in OWL/TTL/SHACL externally and loads it into
  Ontos. Decides what the canonical concepts are, how they relate,
  and where SHACL constraints live. Ontos uses their ontology to
  drive asset types, ground Ask Ontos, and feed agents via MCP. See
  [personas-quick-reference.md](personas-quick-reference.md#knowledge-engineer).

## Other {#other-entities}

- **Compliance Policy** {#compliance-policy} — A declarative DSL
  rule that can be referenced by a workflow's `policy_check` step.
  Compliance scoring derives from policy evaluations.
- **Certification Level** {#certification-level} — A configurable
  ordinal scale separate from lifecycle status. Both products and
  contracts carry a current level, inherited level, certified-by/at,
  expiry, and notes.
- **Business Owner** {#business-owner} — A persisted business-side
  owner of an asset, separate from the technical team owner. Used by
  workflow approval steps that route to "business owners" for sign
  off. In the current Ontos version, Business Owners and the
  team-based Owner surface are increasingly presented through a
  single consolidated Ownership panel on data product and contract
  detail pages, with provenance shown for imported (ODCS/ODPS)
  contacts and active business-owner records merged into YAML
  exports for standards compliance.
- **Business Role** {#business-role} — A configurable business-side
  role (e.g., "Head of Sales Analytics") that can be assigned to a
  person and referenced by workflows. Distinct from Ontos's
  authorization roles.

_Last verified against codebase: 2026-05-28_
