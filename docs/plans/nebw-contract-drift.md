# Plan: Contract change-tracking → Asset Review → semver adopt (nebw #2)

> Branch: `nebw-contract-drift` (off `nebw-bugfixes`). Targets `development`.
> Part of the [nebw customer batch](./nebw-customer-batch.md). Deterministic diff + manual semver (no LLM this batch).

## Goal

Detect when an external catalog's schema has drifted from the data contract that governs it, surface the diff through an Asset Review, and let a reviewer adopt the change as either a new contract version (semver-bumped) or an in-place update.

## What already exists (reused, not rebuilt)

- **`ContractChangeAnalyzer.analyze(old_odcs, new_odcs)`** (`utils/contract_change_analyzer.py`) — deterministic diff that returns `version_bump` (major/minor/patch/none), categorized breaking/feature/fix lists, and a summary. This is the semver engine; no LLM needed.
- **`DataContractsManager.build_odcs_from_db(contract_db)`** — serializes a contract to the ODCS dict the analyzer consumes (the `old` side).
- **`ContractCloner.clone_for_new_version(contract_db, new_version, change_summary, created_by)`** (`utils/contract_cloner.py`) — clones a contract into a new version preserving `version_family_id` + `parent_contract_id`, status `draft`.
- **Asset Review** (`db_models/data_asset_reviews.py`, `controller/data_asset_reviews_manager.py`) + workflow `create_asset_review` step (`data/default_workflows.yaml`).
- **Connector schema fetch** (`connectors/databricks.py` `get_asset_metadata().schema_info`) — now includes PK/FK from nebw #4.
- **Asset↔Contract links** — `implementsContract` / `governedBy` relationships (`data_contracts_manager.auto_link_schema_to_assets`).

## Status (updated 2026-08-19)

- ✅ Candidate-ODCS-from-asset helper (`build_candidate_odcs_from_schema_info`) + `replace_contract_schema` on `DataContractsManager`.
- ✅ `ContractDriftManager`: `analyze_contract_drift`, `find_linked_asset_fqn`, `adopt_drift` (severity-gated in-place vs new version), `create_drift_review` (with open-review dedup).
- ✅ Routes: `POST /data-contracts/{id}/check-drift`, `/adopt-drift`, `/create-drift-review`.
- ✅ Unit coverage: detection (none/minor/major), adoption (new-version/in-place/breaking-reject/override-guard/no-drift), review creation + dedup. 11 tests; no cross-test pollution.
- ⬜ **Follow-up:** wire the existing `data_contract_validation` cluster job (which already detects drift) to auto-create reviews. Per decision, drift→review is app-side/on-demand in this PR. The job runs against Lakebase directly with no access to app managers, so auto-creation needs a job-side reimplementation or an app callback — deferred.
- ⬜ **Follow-up:** indirect schema-verification path (no live connection).

## What must be built

1. **Candidate ODCS from live asset** — a helper that turns a connector `SchemaInfo` (columns + PK/FK) into the ODCS `schema`/`properties` shape the analyzer expects, so the *current catalog state* can be diffed against the governing contract. Lives alongside the analyzer or in the contract manager.

2. **Drift-detection service/job** — `workflows/contract_drift_check/` (mirrors `uc_bulk_import` scaffold: yaml + py, configurable params, scheduled). For each contract with a linked asset:
   - resolve the linked asset FQN (via `implementsContract`/`governedBy`),
   - fetch live schema through the connector (or the indirect schema-verification path when no live connection),
   - build candidate ODCS, run the analyzer,
   - if `version_bump != none`, create an Asset Review carrying the diff (change lists + suggested bump + summary), deduped so an open review for the same contract isn't recreated.

3. **Adoption endpoint** — on an approved review, `POST /api/data-contracts/{id}/adopt-drift` with `{mode: "new_version"|"in_place", bump_override?}`:
   - `new_version`: `clone_for_new_version` with the analyzer's suggested (or overridden) bump, then apply the drifted schema to the clone.
   - `in_place`: apply the drifted schema to the existing contract, bumping its `version` per the suggested/overridden level.
   - Manual bump: reviewer may override major/minor/patch. No LLM.

4. **Persist the diff on the review** — store the `ChangeAnalysisResult` (JSON) on the review/reviewed-asset so the UI can render the diff and the adoption step can reuse the computed bump without recomputing.

## Decisions (confirmed)

- **In-place vs new version is driven by the diff severity, not contract status.** If the analyzer reports a **breaking** change (`version_bump == "major"`), adoption is **forced to a new version** — in-place is rejected. For **non-breaking** changes (`minor`/`patch`), the reviewer may choose in-place or new version. A reviewer may still override the bump level within what the severity allows.
- **Live connector only in this PR.** Drift detection covers contracts whose linked asset has a working connector. The indirect schema-verification path is a documented follow-up.
- **Candidate-ODCS helper lives in `DataContractsManager`**, next to `build_odcs_from_db`, keeping ODCS (de)serialization in one place.
- Dedup key for open drift reviews: contract id + still-open review status (don't recreate while one is open).

## Testing

- Unit: candidate-ODCS builder from a `SchemaInfo` fixture; analyzer already has coverage.
- Unit: adoption service — new_version path (clone + schema apply + version) and in_place path, with bump override.
- Unit: drift-detection creates a review only when `version_bump != none` and dedupes.
