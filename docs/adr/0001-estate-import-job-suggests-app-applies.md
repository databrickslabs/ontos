# Estate Import: a Databricks job generates Suggestions into Postgres staging, the app applies them

Estate Import must handle estates of tens of thousands of tables (some customers will import everything), which rules out in-app enumeration: connector `list_assets` caps at 10k and has no server-side paging. Suggestion generation therefore runs as a Databricks job per Phase that enumerates via bulk metadata queries (UC `system.information_schema`, BigQuery `INFORMATION_SCHEMA`) and writes Suggestions **directly into Ontos Postgres staging tables**, because the review UI needs filtered, paged, editable access to them. Apply runs **in the app**, not the job, so every write goes through the existing managers (identity matching, domain associations, audit, provenance).

## Considered Options

- **Job → Delta → app ingest → Postgres** (the Metagen pattern): rejected; a second hop and retry/ingest state machine for no benefit, since the review surface lives in Postgres anyway.
- **In-app background thread** (the Schema Importer async pattern): rejected; does not scale to full-estate enumeration and competes with the app's own request handling.
- **Job also applies** (the `uc_bulk_import` pattern): rejected; bypasses manager-level invariants and duplicates entity-creation logic outside the app.
