# Plan: Fix Schema Importer table expansion (Databricks UC tree recursion)

> Source PRD: [docs/prds/prd-schema-importer-table-expand-recursion.md](../docs/prds/prd-schema-importer-table-expand-recursion.md) — GitHub [#286](https://github.com/databrickslabs/ontos/issues/286)
> Tracking issue: [#287](https://github.com/databrickslabs/ontos/issues/287)

## Architectural decisions

Durable decisions that apply across all phases:

- **Path-depth contract for connector listing** (single source of truth across connectors):
  - 0 segments → list catalogs / projects / databases.
  - 1 segment → list schemas / datasets in that container.
  - 2 segments → list assets (tables, views, materialized views, streaming tables, functions, models, volumes, routines, etc.) in that schema.
  - **3 or more segments → return empty list** (path identifies a leaf asset; not a container).
- **Where columns come from**: never from listing. Columns are projected into the navigable tree by the **schema-import browse layer**, sourced from the connector's metadata accessor (`schema_info.columns`).
- **Browse node shape**: no new fields on the existing browse-node contract. Column rows reuse `node_type = "column"`, `has_children = false`, and a stable path of `parent_path + "." + column_name`.
- **Failure model**: hard listing failures continue to surface via the existing `error` / `error_detail` channel on the browse response. Metadata-fetch failures during column enrichment are logged and degrade silently to listing-only nodes — never a top-level error.
- **No persistence changes**: the bug is purely in-memory tree construction; no migrations, no backfill, no change to imported asset shape.
- **No frontend changes**: the schema-browser tree already requests children by path and renders whatever browse returns; the column icon is already mapped.
- **In-scope connectors**: Databricks UC (bug fix + column enrichment) and BigQuery (column enrichment only — listing already correct). Snowflake remains a stub. Kafka and Power BI are out of scope for column enrichment.

---

## Phase 1: Stop recursive table expansion and surface columns instead

**User stories**: 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12 (from PRD)

### What to build

A single end-to-end vertical slice that fixes the visible bug and lands the supporting structure for column-level browsing:

- Bring the Databricks UC connector's listing entry point in line with the path-depth contract above. A path with three or more dot-separated segments returns an empty list regardless of any asset-types filter. Two-segment behavior is preserved exactly as today.
- Extend the schema-import browse layer so that, after the existing container and asset listing for the current path, it also fetches the connector's metadata for that path and, when `schema_info` exposes columns, appends one column node per column. Apply the standard path convention, mark non-expandable, and deduplicate against listing nodes by path. Wrap the metadata fetch in the same defensive try/except pattern already used for listing — failures are logged and produce a listing-only response.
- No frontend code changes. The existing schema-browser tree, icon map, and search behavior already render the new column nodes correctly.
- Regression and behavior tests as below.

### Acceptance criteria

- [ ] In the Schema Importer UI, expanding a Databricks UC table no longer renders a duplicated list of the parent schema's tables.
- [ ] In the Schema Importer UI, expanding a Databricks UC table that exposes column metadata renders one row per column under the table; column rows are non-expandable.
- [ ] In the Schema Importer UI, expanding a Databricks UC view, materialized view, or streaming table behaves the same as a table when column metadata is available.
- [ ] In the Schema Importer UI, expanding a BigQuery table, view, or materialized view that exposes column metadata renders one row per column under it.
- [ ] In the Schema Importer UI, expanding a Databricks UC schema still renders all of its tables, views, materialized views, streaming tables, functions, models, and volumes (no over-correction / no regression at the schema level).
- [ ] When the metadata fetch for the current path fails, the browse response still returns the listing nodes; no top-level error is surfaced; the failure is logged.
- [ ] Backend unit test: Databricks connector listing call with a three-segment path returns an empty list, regardless of asset-types filter.
- [ ] Backend unit test: Databricks connector listing call with a two-segment path returns the expected schema-level assets (regression guard).
- [ ] Backend unit test: schema-import browse, given a stub connector that returns column metadata for the current path, includes one column node per column with the documented path convention and `has_children = false`, and deduplicates against listing nodes by path.
- [ ] No persisted-data migration introduced; previously imported assets are unchanged.
- [ ] Issue [#287](https://github.com/databrickslabs/ontos/issues/287) acceptance checklist is satisfied.
