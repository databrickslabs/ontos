# PRD: KPI Consistency Across Metric Views

## Problem Statement

A KPI is only useful when everyone computes it the same way. In a real catalog the same KPI ends up defined more than once:

- **Same name, different semantics.** "Revenue" is `SUM(gross_amount)` in one Unity Catalog metric view and `SUM(amount - refunds)` in another. "Active customers" counts a 30-day window in one view and a 90-day window in another.
- **Different names, same semantics.** "Net Sales" and "Net Revenue" are two concepts, or two measures, for one computation.
- **Conflicting links.** One computation is linked to concept A in one view and to concept B in another.

Ontos can't find or resolve these today:

- Nothing compares measure definitions across metric views. The definition is read live from Unity Catalog when a panel opens (#1079); the schema importer stores the schema, statistics, ownership and tags on the asset, but not the parsed spec (`controller/schema_import_manager.py`).
- The parser (`common/metric_views.py`) keeps `source`, `filter`, `joins`, `dimensions` and `measures` with `name`, `expr`, `display_name`, `comment`, `format` and `synonyms`. It drops each measure's `window`, the top-level `parameters` and the join `cardinality`, and skips fields without a `name` (allowed on Runtime 19+). A window difference is invisible.
- Concept creation rejects only an identical IRI in the same collection. #914 plans concept-to-concept overlap from labels, synonyms and definitions; it does not cover measures.
- Apart from term mapping (#469) and MDM matching, Ontos doesn't record a decision like "these two are intentionally distinct", so a detector without one would repeat its warnings forever.

Databricks has no documented feature that flags duplicate or conflicting metrics. Its metric-view advisor agent skill (`databricks/databricks-agent-skills`, `skills/databricks-metric-views/references/metric-view-advisor.md`) checks overlap before proposing a new view: same source table FQN first, then dimension and measure `expr` normalized (whitespace and case ignored, `source.` prefix stripped), names ignored.

## Solution

1. **Definition analysis first.** The measure definition is the primary signal, not its name. Two measures that read the same data, or whose queries are nearly the same, are the main source of semantic divergence, even when their names and concepts differ. Each measure gets a three-level fingerprint (expression, scope, full) built from the parsed spec, with the same normalization the drift detection of #1124 needs, plus a **data footprint** (the source columns it reads and how it aggregates them) and a **similarity score** against the other measures over the same data.
2. **Read-only consistency views.** The concept page lists the measures linked to the concept grouped by fingerprint; the metric view panel shows, per measure, other measures with the same or a similar definition over the same data, and conflicting links. A warning appears when a link would create a conflict.
3. **Worklist with decisions.** A detection job produces candidates (duplicate, near duplicate, variant, conflict, link conflict, unrecognized duplicate) into a store ideally shared with #914; stewards resolve them, and decisions persist.
4. **Resolutions built on existing mechanisms.** Link to the canonical concept, mark as distinct with a reason, deprecate the duplicate asset, propose a definition change (#1124), merge concepts (#704) or assert a SKOS match (#914).
5. **Optional semantic layer.** Embeddings (#1096) and a gated LLM explanation, off by default.

## User Stories

### Data steward

1. As a data steward, I want to see every measure linked to a concept with its definition, so that I can tell whether they all compute the same thing.
2. As a data steward, I want differences highlighted by kind (expression, source, filter, window), so that I don't have to read raw YAML to find why two "Revenue" measures disagree.
3. As a data steward, I want a worklist of duplicate and conflicting KPIs across the catalog, so that I can clean them up systematically.
4. As a data steward, I want to mark two measures as intentionally distinct with a reason, so that the pair isn't proposed again unless one definition changes.
5. As a data steward, I want to link an unlinked duplicate to the concept of the measure it duplicates, so that both are found from the glossary.
6. As a data steward, I want to deprecate a duplicate metric view and point consumers to the canonical one.

### Data modeller

7. As a data modeller, I want a warning when I link a measure to a concept whose other measures compute something different, so that I fix the conflict before it spreads.
8. As a data modeller, I want to propose aligning a measure's expression with the canonical one through a reviewed change request (#1124).

### Glossary owner

9. As a glossary owner, I want two concepts whose linked measures compute the same thing to be proposed as overlapping, so that I can merge them or assert a SKOS match (#914).

### Negative requirements

10. As a user, I never want the worklist to show me a definition I can't read in Unity Catalog.
11. As a steward, I never want a resolution applied automatically, by a rule or by an LLM.
12. As an owner, I never want Ontos to change a metric view definition outside the #1124 change request flow.

## Implementation Decisions

### Prerequisites (phase 0)

- The field-links and asset-type work for #1124: concept links on a metric view (`uc_table`, `catalog.schema.view`) and its measures (`uc_column`, `catalog.schema.view.field`) in `entity_semantic_links`, and a Metric View asset type with status and certification.
- The parser keeps each measure's `window` (`order`, `range`, `semiadditive`, `offset`), the top-level `parameters` and the join `cardinality`. Additive: existing keys and their shapes don't change.

### Fingerprint

| Level | Content |
|---|---|
| Expression | `expr` with references to other measures and dimensions inlined (bounded depth, cycles refused), normalized |
| Scope | expression + effective source (FQN, or normalized source query) + view `filter` + the joins the expression uses, with `cardinality` |
| Full | scope + `window` + `parameters` defaults |

- Normalization in phase 1 is textual, aligned with the Databricks advisor: case and whitespace collapsed, `source.` prefix stripped, join aliases resolved to the join source. A SQL-aware normalizer (`sqlglot`, Databricks dialect) is a phase 3 option; it is a new dependency.
- Window ranges are parsed into (kind, value, unit, inclusive) so `trailing 30 day` and `trailing 30 day exclusive` compare equal (exclusive is the default).
- The module is shared with the drift detection of #1124 (same keys excluded: `display_name`, `format`, top-level `comment`, which Unity Catalog doesn't keep in the stored text).
- A digest per level is stored, plus the normalized components for the diff.

### Data footprint and similarity

Exact fingerprints only catch copies. Two measures over the same data whose queries differ slightly (an extra filter predicate, a different window, `COUNT(DISTINCT customer_id)` vs `COUNT(customer_id)`) are where conflicting numbers come from, so the definition is also compared approximately.

- **Data footprint.** The set of source columns a measure reads (`catalog.schema.table.column`), resolved through the expression, the effective source (FQN, or the tables of a source query), the view `filter` and the joins it uses, together with its aggregation functions. Measures whose footprints overlap are compared; measures over unrelated data never are, which keeps simple expressions on different tables apart. Unity Catalog column lineage can cross-check the footprint where it is available (not verified for metric views).
- **Similarity.** A component-wise comparison of the normalized parts (aggregation, base columns, source, filter predicates split on `AND`, window, joins, parameters) gives a score from 0 to 1 and a per-component diff. Phase 1 compares normalized tokens per component (set overlap); a SQL-aware comparison (`sqlglot`) is the phase 3 option.
- The score and the components that differ are stored on the candidate, so the steward sees why two measures were paired ("same columns and aggregation, filter differs: `status = 'active'` vs none").

### Classification

| Claimed meaning | Full fingerprint | Verdict |
|---|---|---|
| same concept, or same normalized name / `display_name` / synonym | equal | `duplicate` |
| same concept or name | different | `conflict`, with the first level that differs |
| different concepts | equal | `link_conflict` |
| not linked, names differ | equal | `unrecognized_duplicate` |
| any | different; same data footprint and aggregation, only `filter`, `window` or `parameters` differ | `variant` (for example a 30-day and a 90-day "Active customers"): align them, or mark them distinct with a reason |
| any | different; overlapping data footprint and similarity at or above the threshold | `near_duplicate`, with the components that differ |

- An equal expression with a different source is not a duplicate: simple expressions (`COUNT(*)`, `SUM(amount)`) would match everywhere.
- The similarity threshold is a setting (default proposed in implementation, tuned on a real catalog). `variant` and `near_duplicate` are never resolved automatically.
- Name matching reuses the term mapping helpers (`controller/term_mapping/naming.py`: `normalize`, `depluralize`).
- Concept pairs whose linked measures share a full fingerprint become `concept_concept` candidates for #914.

### Storage

- **Phase 1, no migration.** The parsed spec and fingerprints are stored in `AssetDb.properties['metric_view']` of the Metric View asset at import and metadata refresh.
- **Phase 2, one Alembic revision** (proposal, decided in implementation):
  - `semantic_overlap_runs`: id, kind, scope filter, status, stats, timestamps, triggered by (like `term_mapping_runs` and `mdm_match_runs`).
  - `semantic_overlap_candidates`: id, run id, kind (`concept_concept`, `measure_measure`, `measure_concept_link`), subject A and B (entity type + id), fingerprints of A and B, signals (JSON), score, verdict, status (`pending`, `resolved`, `distinct`, `dismissed`), decision (action, reason, canonical IRI), decided by and at, `review_request_id`, `reviewed_asset_id`.
  - A `distinct` decision is keyed on the pair and both fingerprints: it suppresses the pair until either definition changes.
- Whether #914 shares these tables is an open question; the `kind` column keeps the option.

### Detection

- A scheduled in-app job over stored fingerprints: group by full and scope digests, block similarity candidates by shared source columns (only measures whose footprints overlap are scored), block name candidates by normalized tokens. Pure Python; no Spark job needed (catalog sizes of thousands of measures, not verified on a real catalog).
- Incremental checks when a metric view is re-imported, when drift is detected (#1124) and when a measure link changes.
- The job reads Unity Catalog as the app service principal.

### Visibility

- The worklist and the consistency views never show a definition the user can't read in Unity Catalog. Definitions are read as the user (OBO), as the metric view panel does.
- For a view the user can't read, they see only Ontos-level metadata: the asset name, its linked concept and the verdict.

### Resolutions and workflow

| Resolution | Mechanism | Approval |
|---|---|---|
| Link to canonical concept | `entity_semantic_links`; repoint through #704 for a link conflict | steward action, audited |
| Mark as distinct | decision with a required reason (environment copy, regional variant, intentional variant, other) | steward action, audited |
| Deprecate the duplicate | Metric View asset status | existing asset workflows |
| Align the definition | #1124 change request | #1124 review and delivery |
| Merge concepts / SKOS match | #704 merge, #914 match assertions | existing concept workflows |

- Batch review goes through an Asset Review request, as MDM and term mapping already do.
- Permissions: semantic-models READ_WRITE for concept actions, asset ownership or steward role for asset actions.

### LLM and embeddings (phase 3, optional)

- Measure text (name, `display_name`, synonyms, comment) embedded through the #1096 worker; concept vectors from #1054 slice 3.
- Vector neighbours propose `possible_variant` candidates for unlinked, differently named measures; never auto-resolved.
- An LLM explains a conflict in plain language and proposes a verdict. Gated like Metadata Generation (#1227): off by default, admin settings, endpoint allow-list, metadata only (names, expressions, comments; never data), per-run limits.

### API surface (proposal)

- `GET /api/metric-views/consistency?concept_iri=` and `?asset_id=`: grouped measures and diffs.
- `POST /api/semantic-overlap/runs`, `GET /api/semantic-overlap/runs/{id}/candidates`.
- `POST /api/semantic-overlap/candidates/{id}/decision` with the action and reason.
- Errors are `detail = {code, message, params}`, translated in the UI.

## Testing Decisions

### Backend Tests (pytest)

| Area | Level | Cases |
|---|---|---|
| Parser | Unit | `window`, `parameters`, `cardinality` kept; existing keys unchanged |
| Fingerprint | Unit | case, whitespace and `source.` prefix ignored; references inlined; a reference cycle refused; equal expression on another source differs at scope level; 30 vs 90-day window differs at full level; `trailing 30 day` equals `trailing 30 day exclusive` |
| Data footprint | Unit | columns resolved through expression, source query, filter and joins; aggregation captured; unrelated tables never paired |
| Similarity | Unit | score and per-component diff; one extra filter predicate scores high; a different base column scores low |
| Classification | Unit | each verdict incl. `variant` and `near_duplicate`; simple expression on different sources is not a duplicate |
| Storage | Unit | spec and fingerprints stored at import and refresh |
| Decisions | Integration | a distinct pair isn't proposed again; it is again after a definition change |
| Visibility | Integration | a candidate involving a view the user can't read shows no definition |
| Resolutions | Integration | link, repoint, deprecate, change request hand-off |

### Frontend Tests (Vitest + React Testing Library)

- Concept page grouping and diff highlighting; metric view panel hints; link warning; worklist filters and decisions; en and pt.

### End-to-end (manual)

On a workspace with two metric views over the same source: one "Revenue" gross and one net, one "Active customers" with a 30-day and one with a 90-day window, and a copy of a view in a second catalog. Import both, link the measures, run detection, check each verdict, resolve one of each kind, and check that a user without access to one view sees no definition from it.

## Out of Scope

- Algebraic equivalence of expressions (`SUM(a) - SUM(b)` vs `SUM(a - b)`).
- Automatic resolution of any kind.
- BI tool semantic layers other than Unity Catalog metric views, and Genie space SQL expressions.
- Authoring metric views in Ontos (see #1124).

## Further Notes

### Implementation phases

| Phase | Scope | Migration |
|---|---|---|
| 0 | Field links and asset type (#1124), parser extension | none |
| 1 | Fingerprints, data footprint and similarity, stored spec, read-only views, link warning | none |
| 2 | Candidate and decision store, detection job, worklist, resolutions | one revision |
| 3 | Embeddings, gated LLM explanation, ODCS `transformLogic` as a second source, optional `sqlglot` | none expected |

### Dependencies

- #1124: field links, asset type, drift normalization, change requests.
- #914: shared candidate store (to agree); #704: repoint and merge.
- #1096 / #1097 and #1054 slice 3: phase 3 only.
- #869: an optional declared "KPI formula" on a concept, to check linked measures against.

### Open questions

1. Should measure overlap share #914's candidate and decision model, and who owns it?
2. Is a KPI a concept type, or a concept with an #869 "KPI formula" field?
3. Is the concept the source of truth for a KPI, or one certified metric view?
4. Environment copies across catalogs: declare catalog equivalence, or mark them distinct once?
5. Is `sqlglot` acceptable as a new dependency?
6. Should deprecation also write the `system.certification_status` tag? Databricks doesn't list metric views among its supported objects, and it isn't verified on one.
7. Does the Tables API return derived names for measures without a `name` (also #1124)?
8. What default similarity threshold, and should `variant` be reported for every filter or window difference or only when the measures share a concept or name?

### Not verified

- `system.certification_status` on a metric view.
- Unity Catalog column lineage for metric view measures (footprint cross-check).
- Detection job throughput and false-positive rates on a real catalog.
