# PRD: Ontology Term Mapping (Bulk Suggest + MDM-Style Review)

> **Status:** Implemented in PR #483 (delivers v1).
> **Tracking issue:** [#469](https://github.com/databrickslabs/ontos/issues/469)
> **Architecture deviation from original PRD:** the original draft assumed an
> in-workbench bulk Accept/Reject + single atomic Apply path (the "AR-merger"
> design). The shipped feature uses an **MDM-style spawn** path: runs remain
> authoritative; stewards trigger a *Generate Review* action that spawns a
> standard Data Asset Review whose ReviewedAsset rows back-reference the
> suggestion queue. Decisions made in the AR editor sync back to the suggestion
> queue. This document is the canonical, post-implementation PRD.

## Problem Statement

Ontos already lets stewards attach customer-ontology concepts to individual
entities, one at a time. On any Data Product, Data Contract (schema or
property), or Asset detail page, a "Linked Terms" panel offers a single-pick
concept selector that writes one row to the polymorphic semantic-link store.
This is fine for occasional curation, but it does not scale to the realistic
onboarding workflow:

- A steward who has just uploaded — or generated — a customer ontology covering
  hundreds of concepts has no way to bulk-assign those concepts across
  thousands of catalog assets, contract properties, and products.
- There is no AI-assisted "here are 240 columns that look like Customer Name"
  workflow. Every assignment is manually discovered and manually clicked.
- There is no persistent queue, no review handoff between curator and steward,
  and no audit trail of *batches* of assignments — only per-link change-log
  entries.
- Rejected assignments are not remembered. A future suggester would re-propose
  the same wrong matches every time.
- Onyx, a sibling project, has a working term-assignment feature with a
  heuristic suggester, persistent mapping, audit, diff, and rollback. The brief
  was to port that capability into Ontos, adapted to Ontos's data model and
  conventions.

Without this capability, customer ontologies in Ontos remain decorative. They
live in the system but are not effectively *applied* to the catalog. The
promise of ontology-driven governance (impact analysis across business terms,
semantic search, automated compliance) cannot be fulfilled until the
assignment layer is bulk-tractable.

## Solution

A new **Term Mapping** feature with two integration surfaces:

1. **Bulk workbench** (`/term-mapping`) — a steward picks targets (Assets,
   Contract schemas / properties, Data Products) plus one or more customer
   ontologies, runs the suggester, sees per-run stats, and either:
   - Auto-applies high-confidence rows (one click, requires Read-Write), or
   - **Generates a Data Asset Review** (MDM-style spawn) containing one
     ReviewedAsset per suggestion. Stewards triage suggestions one at a time
     inside the standard AR view using a specialised
     `TermMappingSuggestionReview` editor. Each decision (accept / reject /
     clarify, with optional IRI override and comment) calls the term-mapping
     API, which applies the link on accept and forward-syncs the
     ReviewedAsset status.
2. **Inline suggestions** — the existing `ConceptSelectDialog` (used on every
   entity that has a "Linked Terms" panel) gains a "Suggested by term mapping"
   tier. The inline suggester runs the same heuristic engine over a single
   entity (persisted *or* draft) and surfaces the top candidates at pick time.

Both paths land in the existing semantic-links store. No parallel storage, no
duplicate read path on detail pages.

The suggester is heuristic-first: deterministic name normalisation
(snake/camel-case, depluralisation), trigram + SequenceMatcher similarity,
type compatibility, and primary-key / foreign-key hints, with a human-readable
"why" rationale on every suggestion. Engines live behind a `Suggester`
interface so future LLM-as-judge or embedding-based engines are additive.

Per-run traceability comes from two new tables:
`term_mapping_runs` (configuration, ontology contexts, target filter, stats,
status, creator, optional comment) and `term_mapping_suggestions` (one row
per suggestion with status, confidence, reason, engine metadata, decision
metadata, applied-link reference, optional steward IRI override, and
back-pointers to the spawned ReviewedAsset and DataAssetReviewRequest). The
run record powers a single-click **Undo this run** affordance that removes
every link the run created and reverts suggestions back to `accepted`
(re-apply possible) — or `superseded` if a manual link for the same source/IRI
now exists.

Customer ontologies are the sole concept source by default. Rows in the
existing `semantic_models` table (uploaded via Settings or produced by the
Ontology Generator) feed the suggester. The inline suggester additionally
considers any non-internal, non-shipped context (e.g. `urn:demo` for
file-backed demo data) so it stays useful out of the box. The three shipped
internal taxonomies are handled explicitly:
- `urn:taxonomy:ontos-ontology` (Ontos's structural Asset types) is
  **permanently blocked** at the API level.
- `urn:taxonomy:databricks_ontology` and `urn:taxonomy:odcs-ontology` are
  excluded by default and surfaced in the run-config dialog as opt-in
  checkboxes. The shipped Databricks taxonomy is auto-checked when the user
  has zero customer ontologies, so demos and first-time exploration are
  one-click.

## User Stories

### Discovery and entry points

1. Stewards see a **Term Mapping** entry in the main nav (gated by the
   `term-mapping` feature permission).
2. Stewards on any Data Contract / Data Product / Asset detail page see
   inline "Suggested by term mapping" candidates inside the existing
   `ConceptSelectDialog`, without leaving the entity.
3. *(Deferred to follow-up PRD)* A contextual "Run Term Mapping" handoff
   from the Ontology Generator pre-fills the workbench with the just-generated
   ontology.

### Running the suggester

4. Stewards start a new run from the workbench by picking target entity types
   (Asset, Data Contract, Data Contract Schema, Data Contract Property, Data
   Product), an optional asset-type-name filter (defaults to `Column`), and
   one or more customer ontologies. "Use every enabled customer ontology" is
   the default.
5. Shipped taxonomies (`urn:taxonomy:databricks_ontology`,
   `urn:taxonomy:odcs-ontology`) are opt-in per run, surfaced in an "Also
   include shipped taxonomies" disclosure.
6. The internal `urn:taxonomy:ontos-ontology` is never selectable and is
   rejected by the API even if a caller tries to inject it.
7. Stewards can attach an optional one-line comment to capture run context.
8. The run executes synchronously today (background execution is reserved for
   a future enhancement); on completion the workbench shows per-run stats:
   targets, total suggestions, pending, auto-apply, accepted, rejected, links
   created, links skipped.

### Reviewing suggestions (MDM-style spawn)

9. From a run with pending or accepted suggestions, stewards click **Generate
   Review** to spawn a Data Asset Review. They pick the reviewer (defaults
   to themselves), an optional note, and whether to include already-accepted
   rows. The PRD's original "in-workbench bulk Accept/Reject queue" path is
   intentionally *not* shipped; reusing the existing AR editor avoids two
   parallel review surfaces.
10. Each suggestion becomes one ReviewedAsset with
    `asset_type=CONCEPT_MAPPING_SUGGESTION` and FQN
    `term-mapping://{run_id}/{suggestion_id}`. The AR detail view renders the
    specialised `TermMappingSuggestionReview` editor, showing the source
    entity, the proposed concept (label + IRI), confidence bucket, the engine's
    "why" rationale, any warnings, and an optional IRI override field.
11. Stewards triage suggestions one at a time inside the AR view. Each
    accept/reject/clarify calls the term-mapping decisions API, which:
    a. Updates the underlying `MappingSuggestionDb` row.
    b. On accept, immediately writes through the existing semantic-links
       manager so the link appears in the entity's "Linked Terms" panel.
    c. Forward-syncs the corresponding ReviewedAsset status (`approved` /
       `rejected`) so the AR's progress reflects reality.
12. The `Accept & next` affordance advances through the AR's asset list, and
    the AR's existing progress / completion semantics are unchanged.
13. The run requester is notified when a Generate Review action succeeds, so
    the spawn is visible in the standard notifications inbox.

### Auto-apply (bypass review)

14. Suggestions with confidence above the engine's high-confidence threshold
    are marked `auto_apply=true`. Stewards can apply just those rows from the
    workbench with one click (`Apply auto (N)`), without spawning a review,
    when they trust the heuristic for that batch.
15. Apply is per-row on accept (not a single atomic-per-run transaction).
    Each link writes through the semantic-links manager so cache and RDF
    side-effects fire identically to a manual link. Failures are surfaced as
    per-row warnings in the run; the run as a whole does not abort.

### Inline suggestions on entity detail pages

16. When a steward opens the existing concept picker on any entity (Data
    Product, Data Contract, Schema, Property, or Asset / Column), they see a
    "Suggested by term mapping" tier listing top heuristic candidates for that
    entity.
17. Suggestions work for **draft** (not-yet-persisted) entities too: the UI
    sends a synthetic-target hint (`name`, `type_label`, `parent_name`) so
    the suggester can score before the entity has an ID. This applies to
    every call site that hosts the concept picker, including the contract
    wizard's draft schemas and columns.
18. The inline suggester considers customer ontologies plus any non-internal,
    non-shipped context (e.g. file-backed `urn:demo` ontologies). Internal
    indices and shipped opt-in taxonomies remain explicitly filtered.

### Undo and run history

19. Stewards see all recent runs in the workbench sidebar with status and
    timestamp. Selecting a run reveals stats, source ontologies, shipped
    taxonomies, and any error.
20. Admins (and only admins) can **Undo** an `applied` run. Undo removes
    every link the run created (pre-existing manual links are untouched) and
    reverts the corresponding suggestions to `accepted` (re-apply possible),
    or `superseded` when a manual link for the same source/IRI now exists.
21. Per-link audit continues to flow through the existing entity change-log
    infrastructure. Run-level audit is captured in the run record itself.

## Implementation Decisions

### Scope and adjacencies

- **In scope for v1**: bulk term assignment over Assets (including Columns),
  Data Contract schemas and properties, Data Products. Heuristic suggester
  only. Persistent suggestion queue. MDM-style review spawn. Per-row apply
  on accept + auto-apply for high-confidence rows + admin Undo at run
  granularity. Workbench view + inline suggester integration.
- **Out of scope for v1**, documented for follow-up PRDs: LLM-as-judge
  re-rank engine, embedding-based engine, schema-drift watcher, relationship
  / foreign-key suggestions, Ontology Publishing approval workflow,
  Generator → Term Mapping contextual handoff, background async run
  execution, in-workbench bulk Accept/Reject (currently reserved; MDM-style
  spawn replaces it).

### Storage model

- Term assignments continue to live in the existing polymorphic
  semantic-link store. No parallel "mapping" table; no snapshot duplication.
- Two new tables:
  - **`term_mapping_runs`** — run configuration, ontology contexts, target
    filter, stats, status, creator, optional comment, error, timestamps,
    `applied_at`.
  - **`term_mapping_suggestions`** — one row per suggestion with status,
    confidence, reason, engine metadata, decision metadata, optional
    `custom_iri` override, the FK of the link it created (for undo), plus
    back-pointers `review_request_id` and `reviewed_asset_id` for the MDM
    spawn path. These two FKs use `String` (not Postgres `uuid`) to match
    the FK target column types on `data_asset_review_requests` and
    `reviewed_assets`.
- The suggestion queue and run record are persisted; suggestions never
  disappear silently. Rejected suggestions stay for negative-feedback
  consumption by future suggester engines.
- No batch versioning of the link store. Per-link audit comes from the
  existing entity change-log. Run-level audit lives on the run record.

### Ontology selection rules

- **Default for bulk runs**: customer ontologies only (`semantic_models`
  rows mirrored under `urn:semantic-model:*` contexts). All enabled rows
  pre-selected if the user does not pick specific ones.
- **Default for inline suggestions**: customer ontologies *plus* any
  non-internal, non-shipped context (e.g. `urn:demo` file-backed data).
  This keeps the inline tier useful on a fresh install with only demo data,
  while bulk runs stay conservative.
- **Permanently blocked**: `urn:taxonomy:ontos-ontology` (Ontos's structural
  Asset typing schema) and the internal indices `urn:app-entities`,
  `urn:meta:sources`. The manager rejects any caller-supplied list that
  includes them.
- **Opt-in shipped**: `urn:taxonomy:databricks_ontology` and
  `urn:taxonomy:odcs-ontology`. Surfaced as checkboxes in the run-config
  dialog. When the user has zero customer ontologies loaded, the dialog
  pre-checks `urn:taxonomy:databricks_ontology` so first-time / demo usage
  is one click.

### Suggester engine architecture

- **`HeuristicSuggester`** (ported from the Onyx source): deterministic
  name similarity (snake/camel-case normalisation with irregular-plural
  handling, trigram + SequenceMatcher), type compatibility, primary-key /
  foreign-key hints. Scoring formula and reason strings preserved from the
  source so behaviour is reproducible.
- Engines are isolated behind a `Suggester` interface. The `engines/`
  directory plus `engine_metadata` JSON column are scaffolded for future
  expansion (LLM-as-judge re-rank, embedding-based). Only `heuristic` ships
  in v1.
- **Target adapters** (`AssetAdapter`, `ContractAdapter`, `ProductAdapter`)
  translate each Ontos entity into a uniform `TargetEntity` shape
  (`name`, `type_label`, `parent_name`, ...) that engines consume. Each
  adapter implements both `list_targets` (bulk) and `get_target` (single,
  used by the inline suggester). The `get_target` path also supports
  **synthetic targets** built from caller-supplied hints, so draft
  (not-yet-persisted) entities can be scored.

### Apply path

- Accepted suggestions are applied per-row, immediately, through the
  existing semantic-links manager. Cache invalidation and RDF-graph mirror
  side-effects fire automatically.
- The link ID is recorded on the suggestion for undo.
- Suggestions carrying a `NEW:` IRI prefix (proposing concept minting) are
  rejected in v1 with a clear reason. Concept minting is an
  ontology-evolution concern reserved for v2.

### Undo

- Removes only the links recorded on the run; pre-existing links are
  untouched.
- Suggestions revert to `accepted` (re-apply possible) unless a manual link
  for the same source/IRI now exists, in which case `superseded`.
- Each link removal flows through the same per-entity change-log path as a
  manual Linked Terms removal.
- Admin-gated.

### AR integration

- New asset type `CONCEPT_MAPPING_SUGGESTION` with FQN format
  `term-mapping://{run_id}/{suggestion_id}`.
- `TermMappingManager.create_review_for_run` spawns a
  `DataAssetReviewRequest` whose ReviewedAsset rows back-reference the
  suggestion rows. Back-pointers are written on both sides
  (`MappingSuggestionDb.review_request_id` /
  `MappingSuggestionDb.reviewed_asset_id`).
- A specialised `TermMappingSuggestionReview` React component is rendered
  inside the standard AR editor whenever the active ReviewedAsset has type
  `CONCEPT_MAPPING_SUGGESTION`. Decisions made in the editor call the
  term-mapping decisions API, which mutates the suggestion **and**
  forward-syncs the AR's ReviewedAsset status.
- `create_review_for_run` notifies the run's requester through the
  existing `NotificationsManager` so the spawn is visible in the standard
  notifications inbox.

### API surface

- Route group `/api/term-mappings/*`:
  - `POST /runs` — create + run the suggester.
  - `GET /runs?limit=` and `GET /runs/{id}` — list / detail.
  - `GET /runs/{id}/suggestions` — list suggestions.
  - `POST /runs/{id}/decisions` — bulk accept / reject / clarify with
    optional per-row IRI override and comment. Used by both the workbench
    and the AR editor.
  - `POST /runs/{id}/apply?apply_auto=true` — apply all `auto_apply=true`
    suggestions in one call.
  - `POST /runs/{id}/review` — spawn a Data Asset Review.
  - `POST /runs/{id}/undo` — admin-only.
  - `POST /suggestions-for` — inline single-entity suggester (used by
    `ConceptSelectDialog`). Accepts optional `name`, `type_label`,
    `parent_name` hints for synthetic targets.
- Every route is gated by the `term-mapping` feature ID with standard
  Read-Only / Read-Write / Admin levels. Undo requires Admin.

### Frontend architecture

- **`views/term-mapping.tsx`** — workbench: runs sidebar + per-run detail
  pane with stats, sources, and action buttons (Apply auto, Generate
  review, Undo).
- **`components/term-mapping/run-config-dialog.tsx`** — run config dialog.
  Pre-checks Databricks shipped taxonomy when no customer ontologies are
  loaded.
- **`components/term-mapping/generate-review-dialog.tsx`** — spawn dialog
  for the MDM-style review path.
- **`components/term-mapping/suggestion-review.tsx`** — specialised
  editor surfaced inside the AR view for `CONCEPT_MAPPING_SUGGESTION`
  assets.
- **Inline suggester integration** — `ConceptSelectDialog` accepts a
  `mappingSource` prop and adds a "Suggested by term mapping" tier.
  Wired through `BusinessConceptsDisplay` from every call site
  (data-contract-details, data-product-details, schema-form-dialog,
  schema-property-editor, data-contract-wizard-dialog) so both persisted
  and draft entities get inline candidates.
- All four new components are i18n'd with translations for de / en / es /
  fr / it / ja / nl, matching the existing app-wide locale coverage.

### Workflow and notifications

- Term-mapping runs do not require an approval gate to execute (a steward
  already has Read-Write to use the feature).
- A confirmation notification fires to the run's requester whenever
  `create_review_for_run` spawns a DataAssetReviewRequest.
- The adjacent **Ontology Publishing** PRD (separate, deferred) would add a
  real approval gate using the existing trigger / workflow / notification
  stack — same primitives as the data-product and data-contract
  publish-approval workflows.

### Demo data

- Demo presets ship enabled customer ontology rows in `semantic_models`,
  so the workbench is non-empty after `load_demo_data`. The inline
  suggester also consumes file-backed `urn:demo` contexts so concept
  pickers on demo entities show suggestions out of the box.

### Adjacent #1 — Ontology Generator → Term Mapping handoff (separate PRD)

- New "Run Term Mapping" button on the Ontology Generator result view and
  on every published `semantic_models` detail page.
- The button opens the run-config dialog with ontology context and target
  filter pre-filled from the ontology's derivation metadata.
- Optional opt-in automation: on the publishing transition
  (status → `published`), fire a heuristic suggester run whose results
  land in the queue for human review. Disabled by default.

### Adjacent #2 — Ontology publishing approval workflow (separate PRD)

- Introduces an explicit lifecycle on `semantic_models`:
  `draft → pending_approval → published / rejected → retired`. `enabled`
  becomes a derived back-compat field.
- "Request Publishing" route + dialog mirror the existing Request Action
  dialogs for contracts and products.
- A new entity type (`semantic_model`) is added to the process-workflow
  entity-type enum. The existing `ON_REQUEST_PUBLISH` trigger is extended
  to dispatch for the new entity type. A new default workflow
  `ontology-publish-approval` ships in the workflows YAML and is
  modifiable in Settings.
- Approval sets status to `published`, rebuilds the in-memory graph from
  enabled models, and notifies the author. Rejection captures the
  reviewer's reason and notifies the author.
- Draft and pending models are hidden from the term-mapping run-config
  dialog. Only `published` customer ontologies feed the suggester. This is
  the gating mechanism that makes term-mapping safe at scale.

## Known Gaps / Follow-ups

Tracked as separate issues (or marked for follow-up):

- **LLM-as-judge engine** — `engines/` directory + `engine_metadata` schema
  are scaffolded; only `HeuristicSuggester` ships in v1.
  [#485](https://github.com/databrickslabs/ontos/issues/485).
- **Bulk-accept guardrails** — confirm dialog for low-confidence rows when
  bulk-accepting. [#482](https://github.com/databrickslabs/ontos/issues/482).
- **`test_semantic_links_manager.py` pre-existing failures on main** —
  unrelated to term-mapping but exercised by Term Mapping's link writes,
  worth fixing for safety. [#486](https://github.com/databrickslabs/ontos/issues/486).
- **Background async execution** for large runs.
- **Schema-drift watcher** and **FK / relationship suggestions** — v2.
- **Concept minting (`NEW:` IRIs)** — currently rejected; reserved for the
  ontology-evolution PRD.

## Why MDM-style spawn instead of in-workbench review

The original draft of this PRD assumed an in-workbench bulk Accept/Reject
queue with a single atomic Apply. During implementation we deliberately
replaced this with MDM-style spawn for three reasons:

1. **Single review surface.** Stewards already have the AR view as their
   review home. A second parallel queue would have meant two inboxes, two
   sets of filters, two notifications stories.
2. **Clean separation of concerns.** Runs are the authoritative state.
   Reviews are *derived* artifacts that can be deleted, re-spawned, or
   handed off to a different reviewer without affecting the underlying
   suggestion queue. The forward-sync only flows in one direction
   (AR decision → suggestion update + link write); the suggestion queue
   never depends on the AR existing.
3. **Reuse of decision UX.** The AR editor already has progress tracking,
   navigation between assets, comment threads, and notifications. We
   specialise only the per-asset detail panel
   (`TermMappingSuggestionReview`); everything else is the standard AR
   experience.

The trade-off is that "review" is a two-step affordance (run → spawn review)
rather than a single click. We consider this an acceptable cost given the
reuse and consistency gains.
