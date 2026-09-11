# Concepts-v2: Architecture Overview and Build-Decision Record

This document captures the design of the Concepts-v2 work and the reasoning
behind the non-obvious build decisions made along the way. It exists because a
PR diff shows *what* changed but not *why* a given approach was chosen over its
alternatives, and this build accumulated a lot of those choices (the versioning
engine, the two-workflow review model, RDF triple ownership, dialect-portable
dedup, and several UX and governance calls).

It is split into two parts:

1. **Architecture overview** - the system as it now stands.
2. **Decision record (ADRs)** - numbered, grouped decisions in
   Context / Decision / Alternatives / Consequences form.

---

## Table of contents

- [Part 1 - Architecture overview](#part-1--architecture-overview)
  - [1.1 The Define / Explore / Enrich journey](#11-the-define--explore--enrich-journey)
  - [1.2 The concept versioning engine](#12-the-concept-versioning-engine)
  - [1.3 The concept review workflow](#13-the-concept-review-workflow)
  - [1.4 Enrich: Map and Deliver](#14-enrich-map-and-deliver)
- [Part 2 - Decision record (ADRs)](#part-2--decision-record-adrs)
  - [A. Versioning engine](#a-versioning-engine)
  - [B. RDF storage and dedup](#b-rdf-storage-and-dedup)
  - [C. Review workflow and governance](#c-review-workflow-and-governance)
  - [D. Import and the diff engine](#d-import-and-the-diff-engine)
  - [E. Enrich (Map / Deliver)](#e-enrich-map--deliver)
  - [F. Frontend / UX](#f-frontend--ux)
  - [G. Cross-cutting infrastructure](#g-cross-cutting-infrastructure)
- [Part 3 - Deferred to later stages](#part-3--deferred-to-later-stages)

---

# Part 1 - Architecture overview

## 1.1 The Define / Explore / Enrich journey

`/concepts` is a sidebar-nested area (`ConceptsLayout`) with three primary
surfaces plus supporting views (Collections, SPARQL console, Generator,
Hierarchy):

- **Define** (`views/define.tsx`) - three "path cards" to get concepts in:
  **Author** (create a scheme, hand-author), **Generate** (LLM/connection-driven
  via `guided-generate-dialog.tsx`, which composes plain questions into a
  generator prompt and hands off to the existing engine), and **Import** (RDF
  upload). An "In progress" feed shows recent generator runs.
- **Explore** (`views/explore.tsx`) - one browse surface over a single fetch,
  with **List / Tree / Graph** view-modes. Grouping: **Scheme** = `source_context`,
  **Source** = originating file (`source_file`).
- **Concept detail** (`views/concept-detail.tsx`) - status progress bar,
  version history + publish, deprecate-with-successors, linked objects, Turtle +
  in-page SPARQL, reviewer comments.

## 1.2 The concept versioning engine

The versioned unit is `(iri, version)`; `iri` is the stable identity. See
[ADR A](#a-versioning-engine) for the decisions. In short:

- `concept_version` table; exactly one `is_current=true` per `iri`, enforced by
  a partial unique index.
- `rdf_triples.concept_version_id` FK; a triple's owning version is decided by
  its **subject IRI**.
- Publish snapshots the prior version's triples so the diff engine can compare
  old vs new.
- `scheme_membership` is an unversioned many-to-many; there is no scheme-version
  object.

## 1.3 The concept review workflow

Two workflow types cooperate (see [ADR C1](#c1-two-workflow-review-model)):

- **Approval wizard** (`for_request_status_change`) runs *before* submit and,
  on completion, replays the real `/submit-review` call.
- **Process gate** (`on_request_status_change`) holds the concept after submit
  until an approver decides; the workflow decision drives the concept directly.

Lifecycle: `draft -> under_review -> approved -> published -> certified`, with
`changes_requested -> draft` (carrying the reviewer comment), `superseded` for
demoted versions, and reference-gated deprecation/retirement.

## 1.4 Enrich: Map and Deliver

- **Map** - per-scheme coverage matrix (concepts, coverage %, products /
  contracts / assets, pending suggestions, last run) with an inline
  "Review suggested matches" dialog that embeds the shared term-mapping suggester.
- **Deliver** - delivery targets (Tags live via `uc_tag_sync`; Column
  descriptions / UC Glossary as roadmap) and delivery modes (Direct / Indirect /
  Manual, mapped to Ontos' Delivery Mode). The "Deliver to" platform picker is
  driven by enabled connections.

---

# Part 2 - Decision record (ADRs)

Each ADR: **Context** (the problem) / **Decision** (what we did) /
**Alternatives** (what we rejected) / **Consequences** (trade-offs, follow-ups).

## A. Versioning engine

### A1. Version the concept, keyed by `(iri, version)` with a single current row

- **Context.** Publishing a concept must freeze the prior definition so history
  is diffable; without it, edits destroy the old text and there is nothing to
  compare.
- **Decision.** Add a `concept_version` table where `(iri, version)` is the unit
  and `iri` is stable identity. Enforce "exactly one current version per iri"
  with a **partial unique index** `UNIQUE(iri) WHERE is_current`, mirroring the
  Data Products versioning pattern.
- **Alternatives.** (a) A transaction-disciplined "only one current" rule -
  rejected: a bug could produce two-current corruption; the partial index makes
  it *structurally* impossible. (b) Semantic versioning (semver) - rejected for
  now, versions are monotonic integers (see [Part 3](#part-3--deferred-to-later-stages)).
- **Consequences.** The hot set (`is_current`) is a cheap indexed lookup; history
  is retained; a DB-level invariant protects the "current" pointer.

### A2. Triple ownership is decided by the subject IRI

- **Context.** To snapshot a concept's triples per version we must know which
  triples belong to a concept-version.
- **Decision.** A triple's owning `concept_version_id` is determined by its
  **subject IRI**; blank-node closures (owl:Restriction, SHACL shapes, rdf:Lists)
  follow the IRI subject they hang off. Triples whose subject is not a concept
  IRI (scheme headers, semantic-link edges) have `concept_version_id = NULL`.
- **Alternatives.** Tagging every triple explicitly at write time everywhere -
  rejected as invasive and error-prone; subject-IRI ownership is a single rule
  applied consistently.
- **Consequences.** Publish copies the subject-owned triples to the new version;
  `NULL`-owned triples (metadata) are shared and deduped separately (see
  [ADR B](#b-rdf-storage-and-dedup)).

### A3. A demoted prior version is `superseded`, not `deprecated`

- **Context.** When v2 becomes current, v1 needs a status. Reusing `deprecated`
  would wrongly signal "stop using this concept."
- **Decision.** Add `ConceptStatus.SUPERSEDED`. `demote_current` defaults to it:
  the concept stays active, only that *version* is historical. Distinct from
  `deprecated` (stop using the concept) and `retired` (tombstoned).
- **Consequences.** Version history reads correctly; deprecation semantics stay
  reserved for the concept as a whole.

### A4. No "scheme version" object

- **Context.** Schemes group concepts (`skos:inScheme`); do schemes need versions?
- **Decision.** `scheme_membership` is an **unversioned** many-to-many
  `(concept_iri, scheme_iri)`. Versioning happens at the concept grain only.
- **Consequences.** Simpler model; "release" semantics for a scheme are handled
  later by manifests over concept versions, not a scheme-version entity
  ([Part 3](#part-3--deferred-to-later-stages)).

## B. RDF storage and dedup

### B1. Widen `uq_rdf_triple` for per-version snapshots

- **Context.** The original 6-column uniqueness `(s,p,o,lang,datatype,context)`
  *blocks* the publish snapshot copy (same triple, different version).
- **Decision.** Add `concept_version_id` as the 7th column, using Postgres
  `UNIQUE NULLS NOT DISTINCT` so (a) two rows differing only by version are
  allowed, and (b) two `NULL`-owned rows are still treated as duplicates
  (preserving `ON CONFLICT DO NOTHING` dedup for metadata triples).
- **Consequences.** Per-version snapshots coexist; unversioned dedup preserved on
  Postgres. But `NULLS NOT DISTINCT` is Postgres-15+ only - see B2.

### B2. Dialect-independent dedup for unversioned triples

- **Context.** `NULLS NOT DISTINCT` is a no-op on SQLite (the unit-test DB),
  where NULLs are always distinct - so `ON CONFLICT` on the 7-col key never fired
  for unversioned rows and blank-node re-imports duplicated (the reported table
  bloat; caught by an upstream idempotency test after the merge).
- **Decision.** Add a **partial unique index** on the 6-col natural key
  `WHERE concept_version_id IS NULL` (migration `m5`), and point the unversioned
  insert paths (`add_triples_bulk`, and `add_triple` when version is NULL) at it
  with `index_where`. Dedups identically on Postgres and SQLite.
- **Alternatives.** (a) Cap the test to Postgres only - rejected, the suite runs
  on SQLite. (b) Lower coverage/skip the test - rejected, it is a real
  regression guard. (c) Weaken the production constraint - rejected, production
  is correct.
- **Consequences.** No observable production change (redundant with the PG
  constraint for NULL rows); the dedup is now portable and the invariant is
  explicit rather than relying on a PG-only clause.

### B3. Blank-node canonicalization on import (URDNA2015 / RGDA1)

- **Context.** rdflib mints a random blank-node id on every parse, so re-importing
  the same ontology produced different skolemized URIs, never matched the
  uniqueness constraint, and grew the table without bound.
- **Decision.** Canonicalize the graph (`to_canonical_graph`) before persisting
  and before diffing, so identical content yields identical rows and re-imports
  are true no-ops. Only paid when blank nodes are present.
- **Consequences.** Stable, content-derived bnode ids; re-imports dedup; the diff
  engine does not report spurious changes for blank-node-heavy ontologies.

## C. Review workflow and governance

### C1. Two-workflow review model

- **Context.** A concept review needs both a *pre-submit* structured intake and a
  *post-submit* approval gate, and approving the workflow step used to do nothing
  to the concept (a dead end).
- **Decision.** Support two cooperating workflow triggers:
  - **`for_request_status_change`** (approval wizard) runs before submit; its
    `onComplete` replays the real `/submit-review`.
  - **`on_request_status_change`** (process gate) holds the concept after submit;
    the approver's decision drives the concept directly in `resume_workflow`
    (`approve -> approved`, `reject -> draft + reason as reviewer comment`),
    making the workflow the single source of truth for a governed concept.
- **Consequences.** `require_all` named approvers become the mandatory gate; the
  wizard and the async gate are independent and either can be absent.

### C2. Concept-review gate is all-or-nothing (scope = ALL)

- **Context.** Can the review gate apply to specific schemes only?
- **Decision.** The scope model is all/project/catalog/domain - there is **no
  per-scheme opt-in**. When a concept-review process workflow is active, every
  concept submit is governed.
- **Consequences.** Simple and predictable; testing an "ungoverned" path requires
  deactivating the workflow (documented as a clean SKIP in the E2E suite).

### C3. Default-role permissions for Concepts (Scenario C)

- **Context.** No non-admin role could use Concepts: default roles had
  business-glossary but never `semantic-models` (Concept Browser) or
  `term-mapping` (Enrich).
- **Decision.** Grant in `DEFAULT_ROLE_PERMISSIONS`: Data Governance Officer =
  admin (approver/certifier); Data Steward = read_write (author/curate/map, not
  certify/bypass); Data Consumer / Producer = read_only (browse).
- **Consequences.** The persona journeys work out of the box; certification and
  bypass stay admin-gated.

### C4. Reference-gated deprecation and retirement

- **Context.** Deprecating a concept that other things still reference silently
  breaks those references.
- **Decision.** Deprecate/retire is refused with **409** when the reference count
  is > 0 and no successor is supplied; supplying `replaced_by` (deprecate with
  successors) or remapping refs first is allowed. The gate lives in the status
  path, not just the UI.
- **Consequences.** Governance safety; the UI surfaces the 409 as an actionable
  message.

## D. Import and the diff engine

### D1. Re-upload is a versioning event via a diff engine (P0-4)

- **Context.** Re-uploading a scheme file must not blindly overwrite; the steward
  needs to see what changed.
- **Decision.** `concept_diff.py` canonicalizes both incoming and stored graphs,
  groups by concept subject IRI, and returns `{unchanged, modified, new, removed}`
  buckets. The re-upload path shows a **preview** (P1-0) before confirm; removed
  concepts are tombstoned, not hard-deleted.
- **Consequences.** Non-destructive, reviewable re-uploads; the preview is a
  separate `upload_preview` table + confirm step.

### D2. Multi-file merge is additive (all land Draft)

- **Context.** Merging N files into one scheme sent files 2..N through the
  re-upload diff path, which treated not-in-this-file concepts as "removed" and
  deprecated earlier files' concepts.
- **Decision.** A multi-file "one scheme" merge is **additive**: every file's
  concepts land Draft, none are deprecated. Single-file re-upload still runs the
  diff/version path. Gated by an `additive` flag on `/import`.
- **Consequences.** Bulk assembly of a scheme from several files behaves as
  expected; the versioning path is reserved for true re-uploads.

### D3. Uploads land Draft; the bulk changeset gate is off by default (Scenario D)

- **Context.** Should a bulk RDF upload be held behind one aggregate approval?
- **Decision.** **Scenario D**: file imports land as Draft and follow normal
  per-concept approval; the separate "held changeset" approval flow is **not**
  the default. The plumbing exists (carried on a DataAssetReview) but is off.
- **Consequences.** Predictable per-concept governance; the aggregate gate can be
  re-enabled for a customer without new plumbing.

### D4. Record originating filename (`ontos:sourceFile`)

- **Context.** Users want to group concepts by the file they came from, distinct
  from the scheme they belong to.
- **Decision.** Stamp `ontos:sourceFile` per concept on RDF import; "Source"
  grouping keys on it, "Scheme" keys on `source_context`. On modified re-upload
  the sourceFile is refreshed (overwritten), not left stale.
- **Consequences.** Two orthogonal grouping dimensions that do not duplicate each
  other.

## E. Enrich (Map / Deliver)

### E1. "Deliver to" is driven by configured connections

- **Context.** The platform dropdown hardcoded Snowflake / BigQuery / Power BI
  with no backing delivery path, implying capabilities that do not exist.
- **Decision.** Databricks/UC is always offered (the host, and the only live
  delivery path via `uc_tag_sync`); additional platforms come from **enabled**
  connections in Settings > Connectors (deduped by connector type; databricks/uc
  skipped to avoid a duplicate).
- **Consequences.** The list reflects reality; new connections appear
  automatically; the "platforms come from your connections" tooltip is now true.

### E2. Coverage "Last run" keys on the short source-context bucket

- **Context.** Term-mapping runs store `ontology_contexts` as full IRIs
  (`urn:glossary:finance`), but coverage rows key on the short bucket (`finance`)
  from `_extract_source_context`, so the last-run lookup always missed.
- **Decision.** Normalize the run-context map through the same extractor in
  `get_coverage_metrics`, keeping the newest run per bucket.
- **Consequences.** Last-run lands on the right scheme row; the fix lives in one
  place (the extractor is the single source of truth for bucket names).

### E3. Reuse the shared term-mapping suggester inline

- **Context.** Enrich needs a "review suggested matches" flow; the term-mapping
  engine already exists.
- **Decision.** Embed the shared suggester in the Map lane rather than building a
  parallel one; accept-and-apply posts decisions then applies, then refreshes
  coverage + tag stats.
- **Consequences.** One suggester engine; the Map coverage and Deliver tag counts
  stay consistent after an apply.

## F. Frontend / UX

### F1. Concept-detail route is a splat (`browser/*`)

- **Context.** A single-segment route `browser/:iri` 404'd on hard refresh for
  IRIs containing slashes/hash (e.g. `crm#ActiveCustomer`) because the encoded
  slash normalized.
- **Decision.** Use a splat route `browser/*` and read `params['*']`.
- **Consequences.** Deep links and hard refreshes to any concept IRI work.

### F2. Governance status wins over version-row status

- **Context.** A concept's displayed status could come from either the governance
  lifecycle or a version row, and they could disagree.
- **Decision.** Governance status is authoritative for display; version-row
  status is secondary.
- **Consequences.** The status shown matches the lifecycle the user acts on.

### F3. Single-hop status transitions + progress bar

- **Context.** Multi-hop "(via ...)" transitions in the status dropdown confused
  users.
- **Decision.** Offer only the direct next-step transition(s); show a compact
  status progress bar for the full lifecycle and current position.
- **Consequences.** Clear, unambiguous status changes.

### F4. Hide `ontos:*` governance metadata from the Relations panel

- **Context.** Internal governance predicates leaked into the user-facing
  relations view.
- **Decision.** Filter `ontos:*` (and vocab IRIs) out of the Relations panel.
- **Consequences.** The panel shows domain relations only.

## G. Cross-cutting infrastructure

### G1. Proxy-safe query-param routes for IRI-keyed reads

- **Context.** Databricks Apps' proxy collapses `%2F%2F` inside a path segment,
  so IRIs like `https://ontos.example.org/x#Y` on a `{iri:path}` route 301 to a
  mangled path and the backend returns empty - even though the data exists.
- **Decision.** Provide query-param forms (`?iri=`) for IRI-keyed reads
  (`concepts/by-iri`, `semantic-links/by-iri`) and point the frontend at them.
  Upstream independently fixed the same class for business-owners; the merge
  reconciles to the shared route shape.
- **Consequences.** Linked assets, concept detail, and owners load reliably for
  slash/hash IRIs. This is a *pattern* to reuse for any future IRI-keyed read.

### G2. Cap `hatchling < 1.32`

- **Context.** hatchling 1.32.0 enforces "readme path must be within the project
  directory" and rejects this package's `readme = "../README.md"`, breaking every
  hatch-built CI job at metadata generation. Pre-existing on `development`;
  surfaced by a fresh CI run.
- **Decision.** Cap the build requirement to `hatchling>=1.21.0,<1.32`.
- **Consequences.** CI unblocked. Follow-up: relocate the README into `src/` or
  make the field project-local, then lift the cap.

### G3. Live-app E2E harnesses live in the test tree but are not CI gates

- **Context.** Two API-driven E2E suites drive a *running* app over REST; they
  need an app URL + token and cannot run headless in CI.
- **Decision.** Keep them under `src/backend/src/tests/e2e/` with a `*_e2e.py`
  suffix (pytest does not auto-collect them) and have them **SKIP** (exit 2) when
  no `ONTOS_BASE_URL`/token is configured. No hardcoded host/profile.
- **Consequences.** They live with the test tree and are runnable on demand
  without failing headless CI.

---

# Part 3 - Deferred to later stages

These were intentionally scoped out; each has a clear trigger for when it should
land.

| Deferred | Why now / trigger |
|---|---|
| **Release manifests + version pinning** (`release_manifest`, `manifest_pin`) | Not built here; deferred to **P2**, gated on a named version-pinning consumer. A "release" is a manifest over concept versions; the per-concept spine ships first. |
| **Scheme-version object** | Schemes are membership sets, not versioned entities ([ADR A4](#a4-no-scheme-version-object)). Out of scope this stage. |
| **`concept_changeset` bulk-approval gate** (P3) | Parked (Scenario D, [ADR D3](#d3-uploads-land-draft-the-bulk-changeset-gate-is-off-by-default-scenario-d)); plumbing present, off by default. Re-open per customer. |
| **ConceptStatus / EntityStatus lifecycle alignment** | Concepts stay on their own RDF-backed lifecycle; unifying with the platform-wide `EntityStatus` is a future milestone. |
| **Semantic versioning** | Versions are monotonic integers, not semver ([ADR A1](#a1-version-the-concept-keyed-by-iri-version-with-a-single-current-row)); semver was debated and deferred. |
| **README relocation** | See [ADR G2](#g2-cap-hatchling--132); lift the hatchling cap once the readme path is project-local. |

---

*This document was written by Isaac.*
