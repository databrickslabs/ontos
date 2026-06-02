# Asset Model

A quick reference for the unified Asset entity and its ontology-driven type
system. For the longer story behind why the ontology is prescriptive,
see [Ontology and Knowledge Graph](ontology-and-knowledge-graph.md#prescriptive-principle).

## What an Asset is {#what-is-an-asset}

An **Asset** is the abstract reference Ontos keeps to a governed "thing".
The thing might be a UC table, a UC view, a notebook, a model, a
dashboard, a job, a pipeline, an API endpoint, a Power BI report — any
named resource the organization wants to apply governance to. The Asset
is the Ontos-side handle; the thing itself lives in its native system.

Persisted as `AssetDb` (`assets` table). Carries a name, description,
typed `asset_type_id`, optional `domain_id`, platform, `location` (FQN,
URL, or path), JSON `properties`, quick tags, and lifecycle `status`
(`draft` / `active` / `deprecated` / `retired`).

## Ontology-driven Asset Types {#asset-types-ontology-driven}

Asset types are **not** hardcoded in the application. They are derived
from the ontology TTL at startup, per the
[prescriptive-ontology principle](ontology-and-knowledge-graph.md#prescriptive-principle):

1. `ontos-ontology.ttl` is parsed at startup.
2. For every class annotated `ontos:modelTier "asset"`, a row in
   `AssetTypeDb` is created or updated. The row carries the UI icon,
   category, persona visibility, required/optional metadata schemas
   (JSON schemas), and allowed incoming/outgoing relationship types.
3. The frontend's Asset Explorer reads `/api/asset-types` at load — it
   doesn't ship a hardcoded list.

The practical implication: adding a new entity type to your knowledge
model is an ontology edit (new class with the right annotations and a
fresh sync), not a code change. The form fields rendered for that type,
the icon, the relationship picker — all driven by the TTL.

## AssetTypeCategory {#asset-type-categories}

`AssetTypeCategory` is a coarse classification on persisted asset types:

- `DATA` — tables, views, streams, files
- `ANALYTICS` — dashboards, reports, metrics
- `INTEGRATION` — APIs, connectors
- `SYSTEM` — internal infrastructure references
- `CUSTOM` — user-defined types from custom ontology classes

This is separate from `AssetCategory`, which is a connector-level
classification (`DATA` / `COMPUTE` / `SEMANTIC` / `VIZ` / `STORAGE` /
`OTHER`) used by integration adapters when normalizing platform-specific
types to the unified model.

## Entity Relationships {#entity-relationships}

Assets connect to each other — and to other Ontos entities — through
`EntityRelationshipDb` (`entity_relationships` table). The model is
deliberately polymorphic:

- `source_type`, `source_id` — the originating entity
- `target_type`, `target_id` — the destination entity
- `relationship_type` — a string validated against the ontology at
  write time (e.g., `implementsContract`, `hasColumn`,
  `belongsToSystem`, `consumesFrom`, `derived_from`)
- `properties` — optional JSON for relationship-specific metadata

The relationship types themselves are part of the ontology — adding a
new relationship type is an ontology edit. The table is indexed on
both endpoints and on relationship type for fast lookup in either
direction.

## Where Assets show up {#where-assets-show-up}

- **Data Products** — output ports (Deliverables) reference one or more
  Assets as their backing surface.
- **Data Contracts** — schema objects link to asset columns via
  property-level semantic links; assets implement contracts through the
  `implementsContract` relationship.
- **Marketplace** — assets surface through the products they back.
- **Semantic Links** — assets are valid `entity_type` targets for
  semantic links; this is how a concept gets pinned to a UC table.
- **Asset Explorer** — the unified view across asset types, with
  persona-based visibility filtering driven by the
  `ontos:uiPersonaVisibility` annotation on the asset class.

## Asset Reviews {#asset-reviews}

The **Data Asset Review** workflow lets a Producer request that a
Steward formally inspect an Asset before it gets attached to a published
product. Reviews are first-class workflow executions
(`workflow_type = "approval"`, trigger `for_request_review`) that
produce an Agreement on completion. The review captures inspection
notes, sign-off, and an optional approval recommendation.

The feature ships in the current version. The legacy
"datasets" endpoints (`/api/datasets`) are deprecated in favor of
querying assets directly through `/api/assets`.

## Cascade delete {#cascade-delete}

Assets participate in a cascade-delete preview: deleting an asset
identifies dependent entities (children via hierarchical
relationships, products / contracts referencing the asset) so the
caller sees the blast radius before confirming. The preview is
exposed as a tree via `DeletePreviewItem`; the actual delete uses
`CascadeDeleteRequest` and returns a per-asset success / failure list.

## Cross-references {#cross-references}

- [Ontology — prescriptive principle](ontology-and-knowledge-graph.md#prescriptive-principle)
- [Semantic Link — the bridge from a concept to an asset](ontology-and-knowledge-graph.md#three-tier-linking)
- [Data Product — Deliverable / Output Port](data-product-lifecycle.md#output-port) — output ports point at assets
- [End-to-end Flow A — Step 1, "Bring an asset from UC into Ontos"](end-to-end-flows.md#step-a-1)

_Last verified against codebase: 2026-05-28_
