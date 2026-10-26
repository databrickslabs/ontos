# PRD: Metadata Generation (dbxmetagen integration)

> **Status:** Draft — design agreed 2026-10-22, not yet implemented.
> **Tracking issue:** [#1184](https://github.com/databrickslabs/ontos/issues/1184) (slices #1185–#1188)
> **Execution decision:** [`docs/decisions/metadata-generation-execution.md`](../decisions/metadata-generation-execution.md)
> **Vocabulary:** see [`GLOSSARY.md`](../../GLOSSARY.md) — Metadata Generation, Generation Run, Description Suggestion, Apply, Conflict.

## Problem Statement

Most Unity Catalog tables and columns have no description, or a poor one. Writing them by hand does not scale, and stewards have no governed way to bulk-create descriptions in Ontos: there is no review, no approval trail, and nothing that writes descriptions back to Unity Catalog.

[dbxmetagen](https://github.com/databricks-industry-solutions/dbxmetagen) generates good table and column descriptions with LLMs, but it ships its own review app outside Ontos' governance model (roles, Asset Review, process workflows, notifications, audit).

## Solution

Stewards start a **Generation Run** over a selection of UC catalogs, schemas or tables. Ontos runs dbxmetagen as a background job and records the run. Its output becomes **Description Suggestions**, which the steward can browse on the run page (as with the Ontology Generator and Concept Mapper). The steward submits them for review. Ontos puts them in a Data Asset Review, and a default process workflow requests approval and notifies the people involved. Approved suggestions, possibly edited by the reviewer, are **Applied** to Unity Catalog and mirrored onto the Ontos Asset.

## User Stories

1. As a steward, I want to select catalogs, schemas or tables and start a Generation Run, so that I get description suggestions for everything that lacks one.
2. As a steward, I want to optionally regenerate descriptions that already exist, so that I can improve poor ones.
3. As a steward, I want to choose the description style and LLM endpoint (from an allow-list), so that output fits our conventions.
4. As a steward, I want to see all my runs with status, progress and token usage, so that I can track cost and outcome.
5. As a steward, I want to cancel a running run, so that a mistaken selection doesn't burn tokens.
6. As a steward, I want to browse a run's suggestions by table → columns with current vs proposed text, so that I can judge quality before review.
7. As a steward, I want to submit a run's suggestions for review (or have it done automatically on completion), so that approvers get one review request per run.
8. As a reviewer, I want to see a diff of current vs proposed text and edit it before approving, so that I don't have to reject a nearly-right suggestion.
9. As a reviewer, I want to approve, reject or ask for clarification per suggestion, so that partial acceptance is possible.
10. As a requester, I want to be notified when the review is created and when it completes, with a summary of what was applied, skipped and conflicting.
11. As a data owner, I want a suggestion not to overwrite a description someone changed after the run, so that manual edits are never lost silently.
12. As an admin, I want to control limits, data sampling and allowed endpoints, so that cost and data exposure stay governed.
13. As an auditor, I want every applied description to record before/after text and approver, so that changes are traceable.

## Implementation Decisions

**Scope (v1)**
- dbxmetagen `comment` mode only. Suggestions carry a `kind` discriminator so `pi` (classification → tags) and `domain` (→ Ontos domain) can be added later.
- Tables, views and columns. Catalog/schema descriptions are out of scope.
- Default: only objects without a UC description. Opt-in "regenerate existing".
- Data sampling (`allow_data`) is off by default. A per-run toggle is only offered when an admin setting permits it; it sends sample rows and column min/max values.
- Even without sampling, dbxmetagen sends aggregate column statistics (null and distinct counts, value lengths), tags and constraints to the LLM. An admin setting (on by default) can turn these off (dbxmetagen `add_metadata`).
- Serving endpoint: the app's `LLM_ENDPOINT` plus an admin allow-list; a run can pick only those.
- Limits (admin-configurable): 500 tables per run (checked at start against what the app SP can list, and again by the job), 1 active run per user. The job's `max_concurrent_runs: 3` is part of its definition.
- The admin settings are stored in `app_settings` (`METADATA_GENERATION_SETTINGS`) and edited from the runs page by feature admins.
- Token usage is not recorded: dbxmetagen only logs it through its MLflow benchmarking, which the job turns off.

**Execution** — see the decision record. The background job `workflows/metagen_generate/` runs as the app SP, with dbxmetagen output in the app's deploy-time catalog and schema (those of the app volume, else `DATABRICKS_CATALOG`.`DATABRICKS_SCHEMA`). A normalized Delta staging table `metagen_results` is ingested by the app through the SQL warehouse. Status comes from the Jobs API, refreshed on demand by the run page and by the `JobsManager` poller as backstop. `ingest_results(run_id)` is idempotent. Cancel cancels the Databricks job run.

**Review**
- Manual "Submit for review" from the run page, plus an opt-in auto-submit on completion. One Data Asset Review per submission (normally one per run; suggestions sent back for clarification can be submitted again). The reviewer is picked at submit time, or defaults to a member of the `DataSteward` role other than the requester (resolved like the workflow's `create_asset_review` step). Nobody reviews their own run.
- New `AssetType.METADATA_SUGGESTION` with FQN `metagen://{run_id}/{suggestion_id}`. It follows the Concept Mapper's review-spawn pattern: suggestion ↔ ReviewedAsset back-pointers, and a `/decisions` endpoint that forward-syncs ReviewedAsset status.
- A `MetadataSuggestionReview` editor component in the AR UI provides the diff and editing.
- New `EntityType.METADATA_GENERATION_RUN` and default workflow `metadata-generation-review` (trigger `on_request_review`): notify requester → `approval` by the assigned reviewer (approver token `reviewer`) → `entity_action: apply_metadata_suggestions` → notify the outcome (a failed apply step tells the requester to apply from the run page). Ontos creates the Data Asset Review itself, because the workflow's `create_asset_review` step can't take a list of suggestions; the generic data asset review workflow is not run for it, so the reviewer doesn't get a second approval request. The reviewer gets a notification linking the review.
- Decisions are made by the review's reviewer (or a feature admin) under the `data-asset-reviews` permissions; the reviewer can edit the text, and leaves an optional comment that the run page shows.
- Per-item outcomes: approved → applied; rejected → closed; needs clarification → back to pending, resubmittable. If the overall approval is rejected, nothing is applied.
- The overall outcome closes the review (Data Asset Review status approved / denied); a closed review takes no more decisions, and suggestions nobody decided leave it, so they can be submitted again.

**Apply**
- Only accepted suggestions of approved reviews are applied. Executed as the app SP on the app's SQL warehouse (the workflow authorizes it): `COMMENT ON TABLE` / `COMMENT ON COLUMN` (tables and views). The reviewer's edit, if any, is what gets written. The description is mirrored to the Ontos Assets located at the FQN (columns: `table.column`). Data contracts are not touched.
- Not applicable: the table or column is gone, or the app SP may not change it (UC permission error on write). Any other failure leaves the suggestion accepted with its error; applying again retries it.
- Pre-flight writability check at ingest, before anyone reviews: suggestions of a table the app SP neither owns (directly or through a group) nor holds `MODIFY` / `ALL_PRIVILEGES` on, or of a view it doesn't own, are Not applicable with the reason. A table whose permissions can't be read is left pending (Apply reports it).
- Conflict check: the UC description is re-read before writing, and a mismatch with the base text marks the suggestion **Conflict** and skips it. Conflicts can be regenerated, or force-applied by an admin.
- Each applied suggestion goes into the change log (on the run, and on the mirrored Asset) with before/after, approver, applier and whether it was forced; each apply is in the audit log with its counts. Undo is deferred, but the before text is in the change log.
- A summary notification (applied / conflicts / not applicable / failed) goes to the run's owner, linking the run.
- A manual "Apply approved" action on the run page serves as fallback and retry; admins also get "Force-apply conflicts".

**Data model** (new Alembic revision, single head)
- `metagen_runs`: user, status, selection, options, Databricks job run id, token usage, error, timestamps.
- `metagen_suggestions`: run, kind, object type, FQN, column, base/proposed/edited text, status (`pending | accepted | rejected | applied | conflict | not_applicable | superseded`), review back-pointers, applied by/at, before/after.

**Permissions** — new feature `metadata-generation` (BUILD group):
- Read-only: view runs.
- Read/Write: start runs and submit for review.
- Admin: settings, force-apply, delete any run.

Review decisions follow the `data-asset-reviews` permissions and the workflow approvers.

**UI**
- `/metadata-generation`: runs list plus a "New run" dialog with UC picker and options.
- `/metadata-generation/runs/:id`: single-column detail with status, tokens, the suggestions tree and actions.
- All locales get the new strings, using the `__TODO__` scaffolding for untranslated ones.

**Retention** — runs are kept indefinitely. The owner or an admin can delete a run, except while it is running or has an open review.

## Testing Decisions

- Manager-level tests against the `db_session` fixture, with the Jobs API and SQL warehouse mocked: run lifecycle, idempotent ingest, review spawn and decision sync, apply including conflict and not-applicable paths.
- Workflow tests for `metadata-generation-review`, covering the approve, reject and needs-clarification paths.
- Frontend checks of runs list → detail → AR editor.
- Per slice, a manual end-to-end run on a dev workspace: small schema → ingest → submit → approve with one edit and one reject → verify UC descriptions, and verify the conflict path by changing a description before Apply.

## Slices

1. **Run + job + ingest**: models/migration, job workflow, start/cancel/list/get, ingest, runs list and detail UI (read-only suggestions), feature id.
2. **Review**: AR asset type, decisions endpoint, review editor, submit, entity type and default workflow.
3. **Apply**: UC description writer, Asset mirror, conflict check, apply entity action, audit/change log, manual and force apply.
4. **Hardening**: limits, sampling gate, endpoint allow-list, pre-flight check, SP grant docs, end-to-end test on a dev workspace.

## Out of Scope

- PII/PHI classification and domain classification (later `kind`s).
- Catalog/schema descriptions; data contract property descriptions.
- Per-domain or per-owner review routing.
- Undo of applied descriptions.
- Contextual "Generate descriptions" actions on Data Products / Contracts.
- dbxmetagen's knowledge base, ontology, metric view and Genie features.

## Licensing

dbxmetagen is under the Databricks License, the same license as Ontos, so using it within the Databricks Services is covered. It is not bundled: the background job installs it at a pinned commit. It is credited in `NOTICE`. Its own NOTICE states that using it implies consent to Databricks collecting usage and tracking information; the user guide (`src/docs/metadata-generation-guide.md`) quotes it.
