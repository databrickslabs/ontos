# PRD: Knowledge Graph View -- consolidate Concepts caching

## Problem Statement

The Concepts feature (collections, concepts, properties, taxonomy stats, semantic links) reads from four parallel caches inside `SemanticModelsManager`:

1. The in-memory RDF `ConjunctiveGraph` (`self._graph`).
2. Direct Python list/object references (`self._cached_concepts`, `self._cached_taxonomies`, `self._cached_stats`).
3. Persistent JSON files under `data/cache/` (`concepts_all.json`, `taxonomies.json`, `stats.json`).
4. A TTL-keyed dict (`self._cache: Dict[str, CachedResult]`) used by `get_concepts_by_taxonomy`.

These layers were added incrementally and never reconciled. The result is observable user-facing brokenness:

1. Mutations (create collection, assign term to collection, link entity to concept, save ontology to collection) update some layers but not others, so the UI shows zero terms in a collection that clearly contains them, missing collections in the graph filter, and links that "do not stick" until a full process restart.
2. The "Rebuild Graph" action in Settings did not actually rebuild every layer -- a duplicate `_invalidate_cache` definition silently masked the canonical one.
3. The persistent JSON files do not survive process restart in any meaningful way (they are rewritten on first read) and add disk I/O on every mutation for no measurable cold-start benefit.
4. Source-context extraction logic (stripping `urn:ontology:`, `urn:taxonomy:`, `urn:glossary:` prefixes) was duplicated in three places and drifted, miscategorising concepts as "Unassigned".

The recently-shipped bug fixes patched the symptoms (single canonical `_invalidate_cache`, helper for source-context extraction, frontend cross-view refresh nonce) but the underlying architecture still has four caches that any future contributor must remember to update in lock-step.

## Solution

Introduce **`KnowledgeGraphView`**: a single, owned, in-memory view layer over the RDF graph that holds all derived Concepts state (concepts list, taxonomies, properties grouped by source, stats, source-context index). The RDF `ConjunctiveGraph` remains the single source of truth for triples; `KnowledgeGraphView` is the only cache of derived projections.

Key behaviours:

- The view is built lazily on first read after process start or after a full invalidation, and incrementally updated on mutations where the delta is cheap to compute (single concept add/remove, single semantic link add/remove, collection rename).
- Mutations that touch many triples (RDF source rebuild, ontology import, bulk delete) trigger a full invalidation; the next read rebuilds the view from `self._graph`.
- `SemanticModelsManager` exposes a single `invalidate(reason: str, scope: Literal["full", "concept", "collection", "links"] = "full")` method. All write paths in `SemanticModelsManager` and `SemanticLinksManager` call it. The TTL dict, the per-attribute `_cached_*` references, and the persistent JSON files are removed.
- The persistent JSON cache files in `data/cache/` are deleted on first run after upgrade and the directory is no longer written to by the Concepts feature.
- The frontend `useKnowledgeGraphStore` refresh-nonce mechanism stays as-is and is documented as the contract for cross-view invalidation.

## User Stories

### End-user

1. As a **Data Steward**, I create a new collection from the Concepts view and immediately see it appear in the collection filter on the graph tab and in the source-context dropdown without refreshing the page.
2. As a **Data Steward**, I add a term to a newly-created collection and see the term count on the collection card update on the next render.
3. As a **Data Producer**, I assign an entity to a concept and the link persists across page reload, browser restart, and `uvicorn` reload.
4. As a **Data Steward**, I generate an ontology and click "Save to collection"; the new collection and its concepts appear in the Concepts view and graph within one render cycle.
5. As an **Admin**, I click "Rebuild Graph" in Settings -> RDF Sources and every Concepts surface (collections list, concepts list, graph view, source filter) reflects the rebuilt state without restarting the server.
6. As a **Data Consumer**, I open the Concepts view cold (first request after process start) and see the full list within the performance budget below.
7. As a **Data Steward**, I rename a collection and the new name appears everywhere the old one was shown without a page refresh.
8. As any user, the source-context label shown next to each concept ("Demo Data", "BITOL ODCS", a custom RDF source name) is consistent across the graph, the list, and the property panel -- never a raw `urn:` string and never the literal "Unassigned" for a concept that does belong to a known source.

### Developer

9. As a **Backend developer**, I add a new mutation that affects concepts, call `manager.invalidate(reason="my-mutation", scope="concept")`, and trust that every read path returns fresh data without my having to enumerate every cache layer.
10. As a **Backend developer**, I read `KnowledgeGraphView` and find one class with one well-typed shape (concepts, taxonomies, properties_grouped, stats, source_index) -- not three sibling attributes plus a TTL dict plus on-disk JSON.
11. As a **Backend developer**, I write a unit test for derived data by constructing an in-memory `KnowledgeGraphView` from a small triple fixture, with no SQLAlchemy session, no FastAPI app, and no temp filesystem.
12. As a **Frontend developer**, I bump `useKnowledgeGraphStore.refreshNonce` after a mutation and trust that all subscribed views refetch.
13. As a **Reviewer**, I see one cache-invalidation call site per mutation in `SemanticModelsManager` and `SemanticLinksManager`, not three.
14. As an **On-call engineer**, I read a single `cache.invalidate` log line per mutation that includes `reason`, `scope`, and elapsed rebuild time when a rebuild fires.

## Implementation Decisions

### New module

- New module `src/backend/src/controller/knowledge_graph_view.py` exposing `class KnowledgeGraphView`. The class owns: `concepts: list[ConceptDTO]`, `taxonomies: list[TaxonomyDTO]`, `properties_grouped: dict[str, list[PropertyDTO]]`, `stats: TaxonomyStatsDTO`, `source_index: dict[str, str]` (concept IRI -> source-context label), and a private `_dirty: set[Literal["concepts", "taxonomies", "properties", "stats"]]` for incremental rebuild tracking.
- The view is constructed from a `ConjunctiveGraph` reference and a small `SourceContextResolver` (the existing `_extract_source_context` helper, promoted to a top-level function in `knowledge_graph_view.py`).
- `KnowledgeGraphView.rebuild(scope: str)` recomputes the requested slice. `KnowledgeGraphView.snapshot()` returns an immutable named-tuple view for read paths.

### `SemanticModelsManager` changes

- `self._graph` (the rdflib `ConjunctiveGraph`) stays. Everything else cache-related is removed: `self._cached_concepts`, `self._cached_taxonomies`, `self._cached_stats`, `self._cache: Dict[str, CachedResult]`, the persistent JSON read/write paths, the duplicate-defended `_invalidate_cache`.
- New attribute `self._view: KnowledgeGraphView` holds the single derived view. All `get_*` methods (`get_concepts_grouped`, `get_properties_grouped`, `get_stats`, `get_concepts_by_taxonomy`) read from `self._view.snapshot()`.
- New method `self.invalidate(reason: str, scope: str = "full")`. All write paths call it. The legacy `_invalidate_cache` name is kept as a thin alias for one release for any external callers, then removed.
- `rebuild_graph_from_enabled` calls `self.invalidate("rebuild-graph", scope="full")` after rebuilding `self._graph`. The defensive `db.expire_all()` stays.

### `SemanticLinksManager` changes

- `add` and `remove` call `manager.invalidate(reason="semantic-link-add"/"semantic-link-remove", scope="links")`. The current direct calls to `_invalidate_cache` are replaced.

### Persistent cache cleanup

- On first startup after upgrade, a one-shot cleanup deletes `data/cache/concepts_all.json`, `data/cache/taxonomies.json`, `data/cache/stats.json` if they exist, and removes the empty `data/cache/` directory if no other features use it. Cleanup is idempotent and gated on a startup task.

### Source context

- The existing `_extract_source_context` static helper moves to `knowledge_graph_view.py` as `extract_source_context`. The three previous duplicated `if/elif` blocks (already collapsed in the bug-fix round) call into the same function from one place.

### Frontend

- `src/frontend/src/stores/knowledge-graph-store.ts` (`useKnowledgeGraphStore`) stays. It is documented in the store file header as the contract for "I just mutated something on the backend, all Concepts-related views should refetch".
- `business-terms.tsx`, `ontology-home.tsx`, and `ontology-generator.tsx` keep their `bumpKnowledgeGraphRefresh` calls; no UI behaviour change.

### Performance targets (concrete)

- Cold first-read of `GET /api/semantic-models/concepts-grouped` against a fixture of 10k concepts, 50 collections, 500 properties: <= 400 ms p95 on the dev workspace.
- Warm read of the same endpoint after invalidation `scope="concept"` (incremental rebuild of one concept): <= 50 ms p95.
- Warm read after `scope="full"` invalidation (lazy full rebuild on next request): <= 400 ms p95 (same as cold).
- Steady-state warm read (no invalidation): <= 15 ms p95.
- Memory ceiling for `KnowledgeGraphView` at the 10k-concept fixture: <= 80 MB resident.

### Compatibility and migration

- No schema migration. The change is internal to the manager and removes on-disk JSON files.
- `_invalidate_cache(reason)` remains as a deprecated alias delegating to `invalidate(reason, scope="full")` for one release; it logs a deprecation warning.
- The `/api/semantic-models/refresh-graph` route signature is unchanged.

## Testing Decisions

Good tests verify external behaviour (API responses, view contents after a sequence of mutations) rather than which cache attribute was touched. The new `KnowledgeGraphView` is small and pure enough to deserve dedicated unit tests independent of FastAPI and SQLAlchemy.

### Modules to test

1. **`KnowledgeGraphView` unit tests** (`src/backend/src/tests/unit/test_knowledge_graph_view.py`): construct from a small in-memory `ConjunctiveGraph` triple fixture; assert `snapshot()` shape; assert `rebuild(scope=...)` recomputes only the requested slice and leaves the others byte-identical; assert `extract_source_context` for every URN prefix and for the bare-IRI fallback; assert incremental add/remove of a concept and a semantic link.
2. **`SemanticModelsManager` integration tests** (extend `src/backend/src/tests/integration/test_knowledge_routes.py`): every existing test continues to pass; add a regression test that mutates via four different routes (`POST /api/knowledge/collections`, `POST /api/knowledge/concepts`, `POST /api/semantic-links/`, `POST /api/ontology/save-to-collection`) and asserts the next `GET /api/semantic-models/concepts-grouped` reflects the mutation without a manual `refresh-graph`.
3. **Rebuild regression** (`test_knowledge_routes.py::test_rebuild_graph_clears_view`): seed concepts, mutate the underlying RDF source, call `POST /api/semantic-models/refresh-graph`, assert `GET .../concepts-grouped` reflects the new RDF source.
4. **Performance smoke** (`src/backend/src/tests/perf/test_knowledge_graph_view_perf.py`, opt-in via marker): asserts the four budgets in the Performance targets section against a generated 10k-concept fixture. Skipped in CI by default; run with `pytest -m perf`.

### Prior art

- `src/backend/src/tests/integration/test_knowledge_routes.py` -- existing 22 integration tests covering CRUD and cache freshness (added during the bug fix round).
- `src/backend/src/tests/integration/test_compliance_routes.py` -- route-level integration test pattern.
- Existing `_NoopAudit` stub pattern from the same test file is reused for the new tests.

## Out of Scope

- Persisting the rebuilt view across process restarts. The cold-read budget is tight enough that this is not needed; revisit if the 10k-concept fixture's cold read exceeds 1 s in production.
- Replacing rdflib's `ConjunctiveGraph` with a custom store. The view consolidation is independent of the underlying triple store and we want to keep that decision reversible.
- Cross-process cache coherence (multi-worker uvicorn). The app currently runs single-process; if/when we move to multi-worker, a pub/sub invalidation channel is a separate PRD.
- Frontend-side caching (TanStack Query, SWR). The current refresh-nonce + on-mount fetch pattern is sufficient for now.
- Generalising `KnowledgeGraphView` to other RDF-backed features. The class is intentionally Concepts-specific; if a second feature needs a similar view layer, factor at that point.

## Further Notes

- The four-cache architecture grew organically: the persistent JSON files were added as an "insurance" against cold-start cost that never materialised; the TTL dict was added before the in-memory references existed and was never removed; the per-attribute references were added when the TTL dict's serialisation cost showed up in a profile. Consolidating into one view is the smallest change that makes the right thing easy and the wrong thing impossible.
- The recent bug-fix round ([prior session]) shipped the minimum-viable invalidation correctness. This PRD is the proper architectural follow-up; without it, the next contributor will hit the same class of bug.
- Performance budgets above are derived from current observed warm reads (~12 ms) and cold reads (~280 ms) on the dev workspace's existing ~3k-concept fixture, scaled with headroom to 10k concepts.
- The `extract_source_context` helper is the right place to add future URN prefixes; centralising it removes the "fix in three places" trap that produced the "Unassigned" miscategorisation bug.
- No i18n changes -- this is a backend refactor with no new user-facing strings. The existing source-context labels and collection names are preserved.
