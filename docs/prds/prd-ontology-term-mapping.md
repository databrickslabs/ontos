# PRD: Ontology Term Mapping (Bulk Suggest & Apply)

## Problem Statement

Ontos already lets stewards attach customer-ontology concepts to individual entities, one at a time. On any Data Product, Data Contract (schema or property), or Asset detail page, a "Linked Terms" panel offers a single-pick concept selector that writes one row to the polymorphic semantic-link store. This is fine for occasional curation, but it does not scale to the realistic onboarding workflow:

- A steward who has just uploaded — or generated — a customer ontology covering hundreds of concepts has no way to bulk-assign those concepts across thousands of catalog assets, contract properties, and products.
- There is no AI-assisted "here are 240 columns that look like Customer Name" workflow. Every assignment is manually discovered and manually clicked.
- There is no review queue: if a suggestion engine existed, there would be nowhere for a steward to triage suggestions over multiple sessions.
- Rejected assignments are not remembered. A future suggester would re-propose the same wrong matches every time.
- There is no audit trail of *batches* of assignments, only per-link change-log entries — making it hard to answer "what did Tuesday's mapping run change?" or to roll back a single bad run.
- Onyx, a sibling project, has a working term-assignment feature with a heuristic suggester, persistent mapping, audit, diff, and rollback. We have an explicit brief to port that capability into Ontos, adapted to Ontos's data model and conventions.

Without this capability, customer ontologies in Ontos remain decorative. They live in the system but are not effectively *applied* to the catalog. The promise of ontology-driven governance (impact analysis across business terms, semantic search, automated compliance) cannot be fulfilled until the assignment layer is bulk-tractable.

## Solution

Introduce a new top-level "Term Mapping" feature under the **Govern** group: a workbench where a steward selects targets (Assets, Contract schemas / properties, Data Products) and one or more customer ontologies, runs a suggester, reviews the proposed concept assignments in a persistent queue, accepts or rejects them in bulk (with the option to override the suggested concept IRI per row), and applies the accepted set as one atomic run. Applied assignments land in the existing semantic-links store and immediately appear in the existing "Linked Terms" panels on the affected entity detail pages — no parallel storage, no new shape to read elsewhere.

The suggester is heuristic-first: deterministic name-similarity, type-compatibility, and primary-key / foreign-key hints, with a human-readable "why" rationale on every suggestion. For mid-confidence candidates, an optional LLM-as-judge re-rank uses the existing Databricks Foundation Model client to disambiguate. Embedding-based semantic ranking is documented as a v2 enhancement.

Per-run traceability comes from two new entities: a persistent **suggestion queue** (status `pending` / `accepted` / `rejected` / `applied` / `superseded`) and an **apply run record** that captures the run's configuration, statistics, and the list of links it created. The run record powers a single-click "Undo this run" affordance. Per-link audit continues to flow through the existing entity-change-log infrastructure. The source repo's snapshot-per-version model is intentionally not ported — Ontos's per-row link store is already the source of truth, and duplicating it would create two diverging stores.

Customer ontologies are the sole concept source. Rows in the existing `semantic_models` table (uploaded via Settings or produced by the Ontology Generator) feed the suggester by default. The three shipped internal taxonomies — `ontos-ontology` (Ontos's structural Asset types), `databricks_ontology`, `odcs-ontology` — are excluded by default. The Ontos structural ontology is permanently blocked at the API level; the other two can be explicitly opted into per run for the rare case where shipped platform vocabulary is legitimately assignable.

Two adjacent enhancements are documented in this PRD but built as separate follow-ups: an **Ontology Publishing approval workflow** that adds a steward review gate between draft (uploaded / generated) and published (loaded into the graph and selectable in the term-mapping suggester), and a **Generator → Term Mapping handoff** that contextually launches a mapping run pre-filtered to the catalog the ontology was derived from.

## User Stories

### Discovery and entry points

1. As a steward, I want a new "Term Mapping" entry under the Govern group of the main navigation, so that I can find the bulk-assignment workbench without hunting through entity detail pages.
2. As a user without the term-mapping permission, I want the navigation entry hidden, so that I am not shown features I cannot use.
3. As a steward on any Data Contract / Data Product / Asset detail page, I want a small "N pending suggestions" badge near the existing Linked Terms panel that deep-links into the workbench filtered to this entity, so that I can jump from "what's pending here?" to the review queue.
4. As a steward who has just generated or uploaded a customer ontology, I want a one-click affordance to launch a mapping run pre-scoped to that ontology and the source catalog, so that I do not have to re-enter context I just used (deferred to follow-up PRD; entry point reserved).

### Starting a suggester run

5. As a steward, I want to start a new run by selecting targets across one or more entity types (Assets / Contract schemas / Contract properties / Data Products), so that I can scope a run to whatever curation pass I am doing.
6. As a steward, I want to scope target selection by Domain, Catalog, Schema, Tag, or a specific Contract / Product, so that I can target precisely the slice I am curating.
7. As a steward, I want to pick one or more customer ontologies (rows from `semantic_models` with `enabled=true`) as the concept source, so that the suggester only proposes terms from the vocabularies I have approved.
8. As a steward, I want all enabled customer ontologies pre-selected by default, so that the most common case is one click.
9. As a steward, I do not want to see Ontos's internal structural ontology (`ontos-ontology`) in the picker, so that I cannot accidentally try to assign Asset-typing classes (Table, Column) as if they were domain concepts.
10. As a steward, I want a collapsed "Include shipped taxonomies" disclosure with `databricks_ontology` and `odcs-ontology` available as opt-in checkboxes, so that I can include platform vocabulary in the rare cases where it is appropriate.
11. As a steward, I want to toggle the LLM-as-judge re-rank on or off per run, so that I can control LLM cost.
12. As a steward, I want a one-line description / comment field on the run, so that I can capture the curation context for audit ("Q3 retail onboarding — orders schema").
13. As a steward, I want the run to start immediately and execute in the background, so that I can leave the page and check back later.
14. As a steward, I want to see a live status badge on the run (`suggesting → suggested → applying → applied / undone`) so that I know when results are ready.

### Reviewing suggestions

15. As a steward, I want suggestions grouped by source entity (e.g. all suggestions for one contract property listed together), so that I can curate one entity at a time.
16. As a steward, I want to filter the queue by status (`pending` / `accepted` / `rejected`), confidence range, source entity type, source domain, and ontology, so that I can drive through a large queue in passes.
17. As a steward, I want each suggestion to show a human-readable "why" rationale (e.g. "column name 'cust_email' matches 'Customer Email' by 0.91 trigram similarity; types compatible: STRING ↔ xsd:string"), so that I can judge plausibility quickly.
18. As a steward, I want each suggestion to show the source taxonomy (which customer ontology proposed it), so that I can prefer concepts from the ontology I trust most.
19. As a steward, I want bulk Accept and Reject buttons over a row selection, so that I can clear a large queue efficiently.
20. As a steward, I want to override the suggested concept IRI on a single row before accepting (pick a different concept via the existing concept picker), so that I can correct a near-miss instead of rejecting it.
21. As a steward, I want auto-apply candidates (suggestions above the high-confidence threshold) pre-marked as accepted but still requiring my final Apply click, so that the easy work is done by default but I am never surprised.
22. As a steward, I want a clear visual signal when a suggestion conflicts with an existing semantic link on the same entity (different IRI for the same source), so that I can decide whether to supersede or skip.
23. As a steward, I want the suggester to skip source entities that are already linked to the proposed concept, so that I never see a re-suggestion of work I have already done.
24. As a steward, I want attribute-level suggestions whose parent entity is unmapped (and not in the same accepted batch) to be flagged with a clear "parent entity unmapped" warning, so that I do not silently land an orphan link.

### Applying a run

25. As a steward, I want a pre-apply summary dialog that shows: count of accepted suggestions per target type, count of rejected, count of warnings, estimated number of new semantic links, and any conflict resolutions, so that I have a final preview before mutating the catalog.
26. As a steward, I want apply to be atomic per run (either all accepted suggestions become links, or none and an error is surfaced), so that a partial failure does not leave my catalog in a half-applied state.
27. As a steward, I want to see the apply-run record listed in a "Recent runs" view with start time, finished time, run config, comment, statistics, and the user who ran it, so that I have a single page to inspect history.
28. As a steward, I want each applied link to immediately show up in the existing Linked Terms panel on the affected entity detail page, so that the rest of Ontos sees my work without delay.
29. As a steward, I want the LLM-as-judge call count, token usage, and rough cost surfaced on the run record, so that I can monitor spend.

### Undoing an applied run

30. As a steward, I want a single-click "Undo this run" action on an applied run, so that I can revert a mass mistake without scripting against the database.
31. As a steward, I want undo to remove only the links the run created and to leave any pre-existing links untouched, so that an undo never destroys other work.
32. As a steward, I want suggestions in the undone run to revert to `accepted` status (so I can re-apply selectively), unless the same source/target has been re-linked manually since, in which case the suggestion is marked `superseded`.
33. As a steward, I want the entity change-log to record each link removal under the same change-log infrastructure that the per-entity Linked Terms panel writes to, so that the per-entity audit story is unified.
34. As a governance admin, I want to gate the Undo action behind admin permission, so that arbitrary stewards cannot reverse approved bulk runs.

### Auditing and permissions

35. As an auditor, I want every run-create, apply, undo, and individual accept/reject decision recorded in the user-action audit log under a `term-mapping` feature key, so that compliance reviews are traceable.
36. As an auditor, I want per-link create / delete entries in the entity change log to look identical regardless of whether the link came from a manual Linked Terms panel click or from a term-mapping run, so that per-entity history is consistent.
37. As an admin, I want a new feature ID (e.g. `term-mapping`) registered with the standard Read-Only / Read-Write / Admin levels, so that role-based access can be configured per organisation.
38. As an admin, I want the run-create + run-apply actions gated to Read-Write, the Undo action gated to Admin, and the per-entity badge + run history list gated to Read-Only, so that low-trust users can monitor without mutating.

### LLM consent and cost

39. As a steward enabling LLM-as-judge for the first time, I want a one-time consent dialog explaining that selected concept names and source-column metadata will be sent to the configured Databricks Foundation Model endpoint, so that I make an informed choice in line with existing LLM consent patterns in Ontos.
40. As a steward, I want the LLM-as-judge toggle on the run-config dialog to remember my last choice per user, so that I am not re-prompted every run.
41. As a steward, I want to see, on the run config dialog, an estimate of how many LLM calls will happen given the current target selection, so that I can pre-size the cost.

### Customer ontologies as the concept source

42. As a steward, I want the suggester to consider only concepts from customer ontologies (`semantic_models` table), so that the platform's internal Asset-typing schema cannot be assigned to my data.
43. As a steward, I want an attempt to include the internal `ontos-ontology` context (via an API client) rejected with a clear error, so that no out-of-band caller can bypass this rule.
44. As an admin, I want to opt-in `databricks_ontology` per run, so that genuinely platform-level vocabulary (Cluster, Job) can be assigned where appropriate.
45. As an admin, I want disabled customer ontologies (`enabled=false` in `semantic_models`) hidden from the picker, so that retired vocabularies do not pollute suggestions.

### Demo experience

46. As an evaluator running the retail demo preset, I want at least one customer ontology pre-seeded in `semantic_models` with `enabled=true`, so that the workbench has candidate concepts on first load.
47. As an evaluator, I want a pre-seeded completed apply run with a handful of suggestions across an Asset, a Contract, and a Product, so that the Recent Runs view and the per-entity badges are non-empty.

### Search and discoverability

48. As any user, I want apply runs to appear in global search (so I can find "Q3 retail onboarding"), so that auditors can locate runs by free text.
49. As any user, I do not want individual suggestions to appear in global search, so that the index stays useful.

### Adjacent: Generator → Term Mapping handoff (follow-up PRD)

50. As a steward who has just generated a customer ontology with the Ontology Generator, I want a "Run Term Mapping" button on the generator result view that opens the run-config dialog pre-filled with the new ontology and the catalog the ontology was derived from, so that I can go from generation to assignment in one motion.
51. As an admin, I want an opt-in setting where ontology publication automatically triggers a heuristic-only suggester run (no auto-apply), so that newly published vocabularies arrive with a ready-for-review queue.

### Adjacent: Ontology publishing approval workflow (follow-up PRD)

52. As an ontology author, I want my newly generated or uploaded customer ontology to start in a `draft` state visible only to me, so that I can iterate before others see it.
53. As an ontology author, I want a "Request Publishing" action mirroring the existing Request dialogs for contracts and products, so that I use a familiar promotion pattern.
54. As an ontology author, I want submitting the request to fire a process-workflow trigger that notifies the governance role, so that the right reviewers are alerted automatically.
55. As a steward in the governance role, I want a notification with a deep link to the candidate ontology's preview, so that I can review and approve or reject in one navigation.
56. As a steward, I want approval to flip the ontology to `published`, load it into the in-memory RDF graph, and notify the author, so that the change is immediately reflected for everyone (including the term-mapping suggester).
57. As a steward, I want rejection to flip the ontology back to a working state with my comments captured and the author notified, so that the author has clear next steps.
58. As any user with semantic-model write access, I want draft ontologies hidden from the term-mapping run-config dialog, so that unreviewed vocabularies cannot accidentally be applied.
59. As an admin, I want the publish workflow to be a default workflow shipped in the standard workflows YAML and modifiable in Settings, so that organisations can adapt the approval path to their governance structure.

## Implementation Decisions

### Scope and adjacencies

- **In scope for v1**: bulk term assignment over Assets (including Columns), Data Contract schemas and properties, Data Products. Heuristic suggester + optional LLM-as-judge re-rank on mid-confidence candidates. Persistent suggestion queue. Apply + Undo at the run granularity. New top-level workbench view under Govern.
- **Out of scope for v1** but documented for follow-up PRDs: relationship / foreign-key suggestions, schema-drift watcher, auto-derive mapping from ontology, embedding-based semantic suggester, Ontology Publishing approval workflow, Generator → Term Mapping handoff.

### Storage model

- Term assignments continue to live in the existing polymorphic semantic-link store. No parallel "mapping" table; no snapshot duplication. The source repo's snapshot-per-version model is rejected in favour of Ontos's per-row store plus per-link change-log.
- Two new tables: a **suggestion queue** (one row per suggestion with status, confidence, reason, engine metadata, decision metadata, applied-link reference, optional steward IRI override) and an **apply-run record** (run configuration, ontology contexts, target filter, stats, the ordered list of links the run created, and the user who ran it).
- The suggestion queue and apply-run record are persisted; suggestions never disappear silently. Rejected suggestions stay for negative-feedback consumption by future suggester runs.
- No batch versioning. Per-link audit comes from the existing entity change-log infrastructure. Run-level audit comes from the existing user-action audit log under a new `term-mapping` feature key.

### Ontology selection rules

- Customer ontologies (`semantic_models` rows mirrored into the RDF graph under `urn:semantic-model:*` contexts) are the default concept source. All enabled rows pre-selected.
- The internal `urn:taxonomy:ontos-ontology` context is permanently blocked. The manager validates every run's context list and rejects requests that include it.
- The remaining two shipped contexts (`urn:taxonomy:databricks_ontology`, `urn:taxonomy:odcs-ontology`) are excluded by default and surfaced under an "Include shipped" disclosure as opt-in.
- Concept lookup uses the existing semantic-models concept search APIs, never the internal ontology-schema manager (which serves Asset typing).

### Suggester engine architecture

- **Heuristic engine** (ported from the Onyx source): deterministic name similarity (snake/camel-case normalisation with irregular-plural handling, trigram + SequenceMatcher), type compatibility, primary-key / foreign-key column hints. Scoring formula and reason strings preserved verbatim from the source so behaviour is reproducible. Three source bugs fixed during the port: the broken "skip already-mapped sources" path, the silent placeholder URI on orphan attributes, and the dual-write-with-swallowed-error pattern (the latter is moot because Ontos has no YAML side-channel).
- **LLM-as-judge engine** (new): fires only for heuristic confidences in the mid-range and only when enabled on the run. Uses the existing Databricks Foundation Model client. Output is a confidence ∈ [0, 1] plus a short rationale. The judge's confidence multiplies the heuristic confidence; the product is rounded to preserve the high-confidence auto-mark threshold semantics from the source.
- Engines are isolated behind a Suggester interface. Adding a new engine (e.g. embedding-based in v2) is additive.
- **Adapters** translate each Ontos target type (Asset / Column, Contract schema / property, Data Product) into a uniform feature shape (`name`, `type_label`, `parent_name`, `is_pk`, `is_fk`, optional sample values) that engines consume. The boundary between Ontos types and engine inputs lives in the adapters.

### Apply orchestrator

- Accepted suggestions are sorted entity-assignment first, attribute-assignment second, so an attribute's domain validation against the freshly-applied entity always passes.
- Each accepted suggestion writes through the existing semantic-links manager so its cache invalidation and RDF-graph mirror side-effects fire automatically.
- The orchestrator runs in a single DB transaction per run. The set of newly-created link IDs is appended to the run record for undo.
- Suggestions carrying a `NEW:` IRI prefix (proposing concept minting) are rejected in v1 with a clear reason. Concept minting is an ontology-evolution concern reserved for v2.

### Undo

- Removes only the links recorded on the run; pre-existing links are untouched.
- Suggestions revert to `accepted` (re-apply possible) unless a manual link for the same source/IRI now exists, in which case `superseded`.
- Each link removal flows through the same per-entity change-log path as a manual Linked Terms removal.
- Gated to admin permission.

### API surface

- A new route group covers run create / list / detail / apply / undo, suggestion list with filters, bulk decision update, and a per-entity "pending suggestions" lookup that powers the badge.
- Every route is gated by a new `term-mapping` feature ID with standard Read-Only / Read-Write / Admin levels. Admin gates the Undo action.

### Frontend architecture

- A new top-level view hosts the workbench (runs list + filter), with a per-run detail view showing the grouped suggestion queue. The run-config dialog covers target selection, ontology context selection (with the shipped opt-in disclosure), and the LLM toggle. An apply-summary dialog gates the destructive Apply.
- A reusable "pending suggestions" badge component is dropped into existing entity detail pages alongside the existing Linked Terms panel. The badge does not duplicate the existing Linked Terms read path; it links into the workbench.
- The bulk Accept / Reject UX reuses the established DQX-suggestions dialog interaction model. Concept overrides reuse the existing concept picker. LLM consent reuses the existing one-time consent dialog.

### Workflow and notifications

- Term-mapping runs do not require an approval gate to execute (a steward already has Read-Write to use the feature). Notifications are emitted on run completion to the run's creator only.
- The adjacent **Ontology Publishing** PRD introduces a real approval gate using the existing trigger / workflow / notification stack — same primitives as the data-product and data-contract publish-approval workflows.

### Demo data

- Each demo preset (retail at minimum, ideally HLS / FSI / MFG / Auto) ships one enabled customer ontology row in `semantic_models` plus one completed apply-run with a handful of suggestions covering an Asset, a Contract, and a Product, so the workbench is non-empty on first load.

### Adjacent #1 — Ontology Generator → Term Mapping handoff (separate PRD)

- New "Run Term Mapping" button on the Ontology Generator result view and on every published `semantic_models` detail page.
- The button opens the term-mapping run-config dialog with ontology context and target filter pre-filled from the ontology's derivation metadata.
- Optional opt-in automation: on the publishing transition (status → `published`), fire a heuristic-only suggester run whose results land in the queue for human review. Disabled by default.

### Adjacent #2 — Ontology publishing approval workflow (separate PRD)

- Introduces an explicit lifecycle on `semantic_models`: `draft → pending_approval → published / rejected → retired`. `enabled` becomes a derived back-compat field.
- "Request Publishing" route + dialog mirror the existing Request Action dialogs for contracts and products.
- A new entity type (`semantic_model`) is added to the process-workflow entity-type enum. The existing `ON_REQUEST_PUBLISH` trigger is extended to dispatch for the new entity type. A new default workflow `ontology-publish-approval` ships in the workflows YAML and is modifiable in Settings.
- Approval sets status to `published`, rebuilds the in-memory graph from enabled models, and notifies the author. Rejection captures the reviewer's reason and notifies the author.
- Draft and pending models are hidden from the term-mapping run-config dialog. Only `published` customer ontologies feed the suggester. This is the gating mechanism that makes term-mapping safe at scale.

## Testing Decisions

A good test in this codebase exercises external behaviour through the manager / route surface, asserts on observable outcomes (DB rows, returned API payloads, audit-log entries), and never reaches into engine internals. Pure-function helpers (scoring, naming normalisation, irregular plurals) are tested directly because their public surface *is* the function.

### Modules tested

- **Heuristic engine** — pure-function tests covering: known scoring formula edge cases at the auto-accept threshold (rounding behaviour); snake / camel / irregular-plural normalisation; primary-key and foreign-key hint detection; the "skip already-mapped sources" path (regression test for source bug 1) verifying that a column with an existing link to concept X is never re-suggested for X; the "orphan attribute" guard (regression test for source bug 2) verifying that an attribute suggestion for a sub-entity whose parent is unmapped is flagged, not silently linked to a placeholder.
- **Adapters** — one focused test per target type (Asset / Contract / Product) using a small fixture, verifying that the produced feature shape matches what the heuristic engine expects, that composite IDs for sub-entities follow the existing semantic-helpers convention, and that disabled / draft ontologies are excluded.
- **Apply orchestrator** — integration tests against a real session verifying: ordering (entity assignments applied before attribute assignments); atomicity (transaction rollback on a mid-run failure); idempotency on re-apply of an already-applied accepted suggestion (no duplicate link rows); rejection of `NEW:` URI suggestions; correct population of the run's `applied_link_ids` for downstream undo.
- **Undo** — integration tests verifying: only the run's links are removed; pre-existing links untouched; suggestions move to `accepted` or `superseded` correctly; entity change-log records the removals; admin permission required.
- **Routes** — minimal happy-path + permission-gate tests per endpoint. Verify the `ontology` context guard rejects requests that include the internal context. Verify the per-entity pending-suggestions badge endpoint returns the right count for a known fixture.
- **LLM-as-judge engine** — uses a stub LLM client. Tests verify: invocation only on mid-confidence range; correct multiplication and rounding of confidences; capture of token / call counters in the run stats; graceful handling of LLM errors (degrade to heuristic-only, do not fail the run).

### Prior art for the tests

- `tests/unit/test_workflow_triggers_*.py` is the model for trigger / workflow wiring tests (used when the publishing-approval PRD is built).
- `tests/integration/test_user_header_override.py` shows the persona-switching pattern for testing role-gated routes.
- The existing data-contracts manager tests exercise the persistent-suggestion pattern (DQX) the term-mapping queue mirrors; review for fixture style.
- Pure-function naming and similarity tests should follow the style of the existing change-analyzer tests, which use small parameterised fixtures.

## Out of Scope

- **Relationship and foreign-key suggestions.** Where Asset–Asset relationship suggestions land (the cross-asset relationship store validated against the ontology) versus where Contract property-level FK suggestions land (the existing contract-property relationship rows) is a real design decision that needs its own PRD.
- **Schema drift watcher.** Detecting that a previously-linked column or property has been renamed or dropped, and re-queueing the affected links as suggestions, is a v2 feature that plugs into the existing workflows infrastructure.
- **Embedding-based semantic suggester.** Requires wiring a Databricks Foundation Model embedding endpoint and is the largest single addition; document but defer.
- **Auto-derive mapping from ontology.** The source repo's "derive entire mapping by name-matching the ontology back to its source tables" path assumes the ontology was LLM-derived from the same tables. Useful but orthogonal.
- **Ontology evolution (the `NEW:` URI prefix).** Minting new concept URIs from suggestions either requires write access to the underlying ontology (TTL editing) or coupling to the Ontology Generator. Reserved for v2.
- **Point-in-time versioning of the entire mapping.** Ontos's per-row store plus per-link change-log is the chosen audit model. If stewards report needing true batch rollback beyond the per-run undo, revisit then.
- **Generator → Term Mapping handoff.** Documented as Adjacent #1; built as a follow-up PRD.
- **Ontology publishing approval workflow.** Documented as Adjacent #2; built as a follow-up PRD. Until that lands, the suggester reads every enabled `semantic_models` row, so organisations relying on the current uploader-only access model should treat ontology upload itself as the trust boundary in v1.

## Further Notes

- The plan companion to this PRD lives at `.cursor/plans/adopt_onyx_term-mapping_into_ontos_ea5044ed.plan.md` and includes the concrete file layout, the architecture and sequence diagrams, the Alembic migration shape, the route shapes, the engine module layout, and the verification smoke list. It is the source of truth for the implementer; this PRD is the source of truth for the *what* and *why*.
- The source repo brief (treated as ground truth for the port) is at `/Users/lars.george/Documents/dev/onyx_ontology/docs/EXTRACT_ONTOLOGY_MAPPING_TO_ONTOS.md`. Three known source bugs (broken existing-mapping skip, orphan-attribute placeholder URI, non-atomic dual-write) are explicitly fixed during the port and have regression tests called out in the Testing Decisions section.
- The Linked Terms read path (the existing per-entity concept-chips panel) is unchanged. After applies, new links appear there automatically. This is intentional — there should be one canonical place to see "what concepts are linked to this entity" regardless of how the link was created.
- The two adjacent PRDs (publishing approval; generator handoff) make this feature dramatically more useful. Implementers building v1 should leave clean extension points for them (in particular: the run-config dialog should expect `ontology_contexts` and `target_filter` as pre-fillable from query parameters, and the suggester should treat `semantic_models.enabled` as the gate today and accept replacing it with `status == 'published'` later without code churn).
- This feature is the assignment substrate that lets ontology-driven impact analysis, semantic search, and automated compliance work end-to-end. Without it those downstream capabilities have no data to operate on. Prioritising v1 unblocks an entire downstream theme.
