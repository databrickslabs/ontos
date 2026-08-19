# Plan: nebw customer batch

> Branch: `nebw-bugfixes`. Six customer-requested features/fixes. Codeword **nebw**.
> Started 2026-08-17.

## PR strategy

- **Base branch is `development`**, not `main`. `nebw-bugfixes` is branched off `development`; all PRs target `development`. (`development` is kept ahead of `main` and is the working integration branch.)
- **Main PR (`nebw-bugfixes` → `development`)** carries the small/medium issues, one commit per issue: #1 (custom UUID), #4 (FK/PK import), #5 (asset-type relationship CRUD), #6 (RDF download fix).
- **Separate PRs off the same branch** for the two large features: #2 (contract change-tracking → review → semver adopt) and #3 (Domains ↔ UC governed tags, bidirectional).

## Status (updated 2026-08-18)

Main PR (`nebw-bugfixes` → `development`) — **all four small/medium issues done & committed**:
- ✅ #1 custom UUID on create (`abc4fad0`) — 26 repo tests
- ✅ #6 RDF export 404 fix (`d9612a97`) — 3 tests; also fixed a second root cause (in-memory existence check)
- ✅ #5 asset-type relationship CRUD (`b9c06da8`) — 5 tests, 132 no-regression
- ✅ #4 FK/PK import from UC (`b6546e82`) — 4 tests, 69 no-regression

Separate PRs (off `nebw-bugfixes`):
- ✅ #2 contract change-tracking → review → semver adopt — branch `nebw-contract-drift`, PR #736
- ✅ #3 Domains ↔ UC governed tags, bidirectional — branch `nebw-domain-uc-sync` (see [nebw-domain-uc-sync.md](./nebw-domain-uc-sync.md))

All six issues implemented with unit coverage. Remaining follow-ups are documented per-feature (cluster-job auto-review wiring for #2; a UC governed-tag reader for #3; indirect schema-verification path).

## Architectural decisions

Durable decisions agreed with the requester:

- **#1 Custom UUID on create — generalized.** Add an optional caller-provided `id` to the shared `CRUDBase.create()` path plus a schema mixin, so every entity can accept an API-only id. Domains is the first consumer. Precedent: `DataProduct` already requires a caller-set id. Server-side default `str(uuid4())` remains the behavior when no id is supplied. API-only (not surfaced in UI). Subdomains are `DataDomain` rows with self-FK `parent_id`, so they inherit this for free.

- **#2 Contract change-tracking — deterministic, manual semver.** Build the change-detection job (check external catalog / indirect schema verification → update Assets), then trigger an Asset Review that diffs asset vs. contract. Adoption creates a new contract version (via existing `contract_cloner.clone_for_new_version()`) or updates in place, with a **manual** major/minor/patch choice. No LLM in the loop this batch (AI-suggested bump is a documented follow-up).

- **#3 Domains ↔ UC governed tags — tag + assign, card documented.** Reality: there is **no public API to create/publish a Discover Domain card** (UI-only, needs `MANAGE DISCOVERY`), and **no native "this governed tag is a domain" boolean**. So:
  - Outbound: create the governed tag (`CREATE GOVERNED TAG` via SQL Statement Execution API) and assign it (Entity Tag Assignments API / `SET TAG`), following the `{parentTag}/{subdomain}` key convention that Discover reads. The final Discover Domain card creation is a **documented manual step**.
  - Inbound: read governed tags back (information_schema / entity tag assignments) and materialize/update `DataDomain` rows via the Asset Review flow from #2.
  - SDK surface is `ws.tag_policies` + `ws.entity_tag_assignments` (NOT `ws.governed_tags.*`). Current tag-sync uses plain UC tags via Spark SQL and must be upgraded to governed tags.

- **#4 FK/PK import.** PK is already modeled on `SchemaPropertyDb` (`primary_key`, `primary_key_position`). FK is **not** modeled — add FK representation, fetch UC table constraints during import (`workflows/uc_bulk_import/`), and surface in the catalog API. UC first; other connectors are follow-ups.

- **#5 Asset-type relationship CRUD.** Relationships are currently read-only, loaded from the Ontos OWL graph (`ontology_schema_manager.get_relationships()`). Add a write path that persists user-defined `ObjectProperty` relationships as triples in `rdf_triples` (custom context, kept distinct from the read-only Ontos context), merged into `get_relationships()` reads, with CRUD routes.

- **#6 RDF download 404.** In-app collections (e.g. business glossaries) exist only as triples in `rdf_triples` keyed by `context_name`; uploaded models exist as `content_text` in `semantic_models`. The export endpoint 404s when no file exists. Fix: for modifiable collections, generate the latest RDF from triples via rdflib (`export_collection_as_turtle` / `_as_rdfxml`) instead of 404.

## Key file map

See per-issue sections; anchors captured during exploration (paths under `src/backend/src/`):

- #1: `models/data_domains.py`, `repositories/data_domain_repository.py`, `common/repository.py` (CRUDBase)
- #2: `db_models/data_contracts.py`, `utils/contract_cloner.py`, `controller/schema_import_manager.py`, `db_models/data_asset_reviews.py`, `controller/data_asset_reviews_manager.py`, `data/default_workflows.yaml`, `controller/jobs_manager.py`, `workflows/uc_bulk_import/`
- #3: `workflows/uc_tag_sync/uc_tag_sync.{py,yaml}`, `models/workflow_configurations.py`, `controller/data_domains_manager.py`, `common/workspace_client.py`
- #4: `db_models/data_contracts.py` (SchemaPropertyDb), `workflows/uc_bulk_import/uc_bulk_import.py`, `controller/data_catalog_manager.py`
- #5: `controller/ontology_schema_manager.py`, `routes/ontology_schema_routes.py`, `controller/entity_relationships_manager.py`, `repositories/rdf_triples_repository.py`
- #6: `routes/semantic_models_routes.py`, `controller/semantic_models_manager.py`, `db_models/rdf_triples.py`, `db_models/semantic_models.py`

## Environment notes

- `databricks-sdk` is a **workflow-only** dependency (installed on the Databricks cluster per each workflow's `requirements.txt`), not in the backend hatch env — cannot introspect it locally.
- `hatch -e dev run` from `src/` currently fails on editable rebuild (readme path `../README.md` resolves outside the project dir).
