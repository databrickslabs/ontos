# Metadata Generation — Execution Model

**Date**: 2026-10-22
**PRD**: [`docs/prds/prd-metadata-generation.md`](../prds/prd-metadata-generation.md)

## Decision

Generation Runs execute [dbxmetagen](https://github.com/databricks-industry-solutions/dbxmetagen) as an Ontos background job (`src/backend/src/workflows/metagen_generate/`), not inside the app process. The job pins dbxmetagen to a reviewed commit (it is not on PyPI), runs it with `apply_ddl=false`, lets it write its own Delta output into the app's deploy-time catalog and schema (those of the app volume, else `DATABRICKS_CATALOG`.`DATABRICKS_SCHEMA`), and finally writes normalized rows to a Delta staging table `metagen_results` keyed by the Ontos run id.

The **app** — not the job — ingests `metagen_results` into its own `metagen_suggestions` table via the SQL warehouse, and derives run status from the Jobs API. The job never connects to the Ontos database.

## Alternatives considered

- **Native in-app LLM loop** (as the Ontology Generator does). Rejected: duplicates dbxmetagen's prompt engineering, batching and sampling logic, and forfeits its improvements; dbxmetagen depends on Spark, which the app does not have.
- **Job writes directly to Lakebase** (as `dqx_profile_datasets` does). Rejected: couples the job to the Ontos schema, fails in local development where the database is not reachable from Databricks compute, and leaves no durable copy of raw results in Unity Catalog.
- **Ingest from a customer-deployed dbxmetagen bundle.** Rejected: no control over versions, run correlation or permissions; two deployments to operate.

## Consequences

- The dbxmetagen output-format adapter lives in one place (the job's normalization step); a dbxmetagen upgrade only touches the job.
- Run status is only as fresh as the last Jobs API refresh: the run page refreshes on demand while open, and the `JobsManager` background poller is the backstop.
- `ingest_results(run_id)` must be idempotent because both paths can call it.
- A SQL warehouse (`DATABRICKS_WAREHOUSE_ID`) is required for ingestion.
- The app service principal needs write access on the app schema and `SELECT` on target tables (see `uc-grants-for-app-sp.md`).
- dbxmetagen is under the Databricks License, the same as Ontos; it is credited in `NOTICE` and installed at runtime, not bundled.
