# PRD: Fix Schema Importer table expansion (Databricks UC tree recursion)

## Problem Statement

When a user opens the Schema Importer, picks a Databricks Unity Catalog connection, and drills into the resource tree, the hierarchy works correctly down to the schema level. The bug appears at the **table** level: clicking the chevron on a table node re-renders the **same set of tables** that already appears under the parent schema. Visually it looks as if the table is itself a schema and contains all of its siblings (and itself) again. Users cannot:

- See the table's columns under the table node.
- Trust the tree structure when picking what to import.
- Tell, at a glance, whether a deeper expansion has produced new content or just a duplicate of the schema.

The result is confusing UX and selection mistakes during import.

## Solution

Make the tree match the conceptual hierarchy:

- Catalog → Schema → Table/View/Function/Model/Volume → Column.
- Expanding a leaf asset (table, view, materialized view, streaming table) shows its **columns** when the connector exposes column metadata, and shows nothing otherwise.
- Expanding a leaf asset never shows other assets from the same schema.

This is achieved by:

1. Teaching the Databricks connector that a fully qualified asset path (three or more dot-separated segments) is a leaf for **listing** purposes — it returns no children from the listing API. This matches the BigQuery connector, which already encodes that semantic.
2. Teaching the schema-import browse layer to fetch the leaf asset's metadata and, when columns are present in `schema_info`, surface them as child browse nodes so expansion is visibly meaningful.

## User Stories

1. As a Data Producer using the Schema Importer, I want expanding a catalog to reveal its schemas, so that I can navigate down the platform hierarchy.
2. As a Data Producer, I want expanding a schema to reveal its tables, views, materialized views, streaming tables, functions, models, and volumes, so that I can choose any asset to import.
3. As a Data Producer, I want expanding a table to reveal its columns when column metadata is available, so that I can optionally include column-level paths in my selection.
4. As a Data Producer, I want expanding a view, materialized view, or streaming table to behave like a table (show columns when metadata is available), so that the tree is consistent across leaf asset types.
5. As a Data Producer, I do not want to see schema-level siblings under a table node, so that the tree does not look recursive or duplicated.
6. As a Data Producer, when a leaf asset has no column metadata available (e.g., a function), I want the node to either be non-expandable or expand to an empty list, so that the UI clearly indicates "nothing more to drill into".
7. As a Data Producer, I want expansion of leaf nodes to be fast (a single metadata fetch), so that browsing remains responsive even on connections with many tables.
8. As a Data Producer using a BigQuery connection, I want the same column-level expansion behavior on tables, views, and materialized views, so that the Schema Importer feels uniform across connector types.
9. As a Data Consumer browsing assets via the importer, I want the visual tree to faithfully represent the platform structure, so that what I select is what gets imported.
10. As a developer extending Schema Importer with a new connector, I want a single, documented contract for "what does listing return at depth N" and "where do columns come from", so that I can implement new connectors without re-introducing this bug.
11. As a developer running unit tests, I want regression coverage that explicitly asserts a deep path returns no listed children and that columns appear via metadata, so that future refactors cannot silently re-introduce the recursion.
12. As an Admin operating Ontos, I want existing imports started before the fix to continue producing the same Ontos asset hierarchy after the fix, so that there is no migration or backfill required.

## Implementation Decisions

### Path semantics for connector listing

- The path passed to a connector's listing call is dot-separated and represents the **container** whose direct children should be listed.
- For Databricks UC: zero segments → catalogs; one segment → schemas in that catalog; two segments → assets in that schema; **three or more segments → empty list** (the path identifies a leaf asset, not a container).
- This brings the Databricks connector in line with the explicit contract documented in the BigQuery connector and with the existing leaf-detection logic in the import-preview path.

### Column children come from metadata, not from listing

- Columns are not "listable" siblings — they are **structural children** that live inside an asset's metadata.
- The schema-import browse layer is the single place that knows how to project columns into the navigable tree. It calls the connector's metadata accessor for the current path and, if `schema_info` returns columns, emits one browse node per column with:
  - A stable, predictable path: parent path joined to the column name with `.`.
  - A node type indicating "column".
  - No further expandability.
- Existing nodes returned by listing are deduplicated against these column nodes by path.

### Browse response shape

- No new fields are introduced on the browse response or on individual browse nodes.
- The existing `node_type`, `path`, `has_children`, and `description` fields are sufficient. Column nodes simply use `node_type = "column"` and `has_children = false`.

### Failure modes

- If the metadata call fails (transient platform error, permission denied for the specific asset), the browse call returns the listing-only nodes as today and degrades gracefully — the expansion is empty rather than the tree being broken.
- The browse response's existing `error` / `error_detail` channel is reserved for hard listing failures; metadata failures for column enrichment are logged but do not surface as a top-level browse error.

### Connectors in scope

- **Databricks UC**: bug fix landed in the connector's listing branch; column enrichment benefits this connector immediately because UC tables/views expose `schema_info`.
- **BigQuery**: already correct on listing; column enrichment in the browse layer adds the same UX benefit for BigQuery tables/views/materialized views.
- **Snowflake**: stub today; nothing to change.
- **Kafka, Power BI**: out of scope for column-level expansion; their leaf assets either have no schema or use a different shape.

### No frontend changes

- The schema-browser tree component already requests children by path from the browse endpoint and renders whatever nodes come back.
- Icons for the new "column" node type are already mapped in the existing icon table.
- No prop, state, or layout changes are required on the frontend.

### No data migration

- This bug only affects in-memory tree construction during browsing. There is no persisted state that needs to be migrated. Already-completed imports are unaffected.

### Backwards compatibility

- The change is conservative: deep paths that previously returned schema-level siblings now return an empty list (or columns when metadata is available). Any caller that depended on the buggy behavior would already have been producing wrong asset hierarchies.

## Testing Decisions

### What makes a good test here

- Tests target **observable behavior** at the connector and browse-controller boundary, not internal helpers.
- Tests do not mock the workspace client at API method-name granularity unless necessary; they prefer patching the connector's narrow `_list_*` helpers or its `get_asset_metadata` so the test reads as a behavioral assertion ("given path X, return Y").
- Tests are deterministic and do not require network or Databricks credentials.

### Modules under test

- The Databricks connector's listing entry point: a path with three or more segments returns an empty list, regardless of the asset types filter.
- The schema-import browse controller: when the connector reports column metadata for the current path, the browse response includes one node per column, deduplicated against listing nodes, with the expected path convention and `has_children = false`.
- A regression-style test: a two-segment path still returns the schema's tables/views/etc. (i.e., we did not over-correct).

### Prior art

- Existing backend test patterns for connectors and controllers in the project — mirror the most lightweight pattern in use (stub connector, in-memory session) rather than introducing a new test framework.
- The BigQuery connector's listing docstring is the de facto prior art for the path-depth contract; tests should treat it as the canonical specification.

## Out of Scope

- Any change to the Schema Importer UI beyond what falls out of correct browse data (no redesign, no new controls, no copy changes).
- Any change to import depth, preview semantics, asset creation, or relationship wiring.
- Snowflake connector implementation.
- Column-level expansion for connectors that do not expose column metadata (Kafka, Power BI).
- Caching of metadata calls; if metadata fetches become a hotspot, that is a follow-up.
- Permissions changes; the existing `schema-importer` feature gating remains as is.

## Further Notes

- Repro: open Schema Importer, pick a UC connection, expand any catalog → schema → table; the previous behavior re-listed the schema's assets under the table.
- Root cause was localized to the Databricks connector's listing branch ignoring path segments beyond catalog and schema; the BigQuery connector documents and implements the correct semantic.
- A short engineering work-item note already exists at `docs/notes/work-item-schema-importer-table-expand-recursion.md`; this PRD supersedes it as the canonical artifact for tracking the fix.
- Follow-up worth considering, but not required for this PRD: a single shared "path → depth role" helper across connectors so the catalog/schema/leaf contract is encoded once instead of per connector.
