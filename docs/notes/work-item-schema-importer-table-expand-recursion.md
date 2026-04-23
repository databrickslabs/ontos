# Work item: Schema Importer — expanding a table shows the schema again

## Problem Statement

In the Schema Importer resource tree (Databricks UC connections), expanding a **table** node does not show columns. Instead, the UI lists the same set of **tables** as under the parent schema, as if the table were another schema container. This breaks selection and mental model: users cannot browse to columns under a table, and the tree looks recursively wrong.

## Solution

Treat a fully qualified table (or other leaf) path as **non-listable** via the same code path that lists all objects in `catalog.schema`. Return no sibling assets from listing for that depth, and populate children from **table metadata** (schema / column list) so expansion shows **columns** (or an empty list if none), consistent with how import preview already avoids re-listing siblings for leaf assets.

## User stories

1. As a governance user browsing UC for import, when I expand a **catalog**, I want to see **schemas**, so that I can navigate the hierarchy.
2. As a governance user, when I expand a **schema**, I want to see **tables, views, and other assets** in that schema, so that I can choose what to import.
3. As a governance user, when I expand a **table** (or view with a column schema), I want to see **columns**, so that I can optionally include column-level paths in my selection.
4. As a governance user, when I expand a **table**, I do **not** want to see other tables from the same schema again, so that I am not confused or misled by duplicate structure.
5. As an operator of BigQuery-backed connections, when I expand a table, I want the same **column** behavior where metadata exists, so that behavior is consistent across connector types that expose `schema_info`.

## Implementation decisions

- **Root cause:** For Databricks, `list_assets` interprets any path with at least two dot-separated segments as `catalog` + `schema` and lists all schema-level assets, ignoring a third segment (the table name). Browse merges that result into children for `path=catalog.schema.table`, producing duplicate tables.
- **Connector fix:** For Unity Catalog paths with **three or more** segments, `list_assets` must return an empty list (leaf FQN: no structural children from listing APIs). This aligns with existing BigQuery connector semantics documented in that connector.
- **Browse API fix:** After container and asset listing in schema import browse, when `get_asset_metadata` for the browsed path returns `schema_info` with columns, append browse nodes for each column (stable path pattern: parent path + `.` + column name, `node_type` column, no further children). Deduplicate against nodes already returned.
- **Import / preview:** No change required; `_collect_items` already documents that leaf assets must not recurse via `list_assets` for siblings.
- **Frontend:** No change expected; the tree already requests children by path from the browse endpoint.

## Testing decisions

- **Good tests:** Assert **observable behavior** — given a three-part UC path, listing must not return schema-wide siblings; given metadata with columns, browse must expose column nodes with correct paths and no `has_children` (or equivalent).
- **Modules to test:** Databricks connector `list_assets` (unit test with mocked workspace client or patched list helpers); optionally `SchemaImportManager.browse` with a stub connector returning canned metadata.
- **Prior art:** Look for existing connector or controller unit tests in the backend test tree; mirror patterns used for other Databricks or connection tests if present.

## Out of scope

- Changing import depth semantics, preview UI, or asset mapping rules.
- Snowflake connector (stub) until implemented.
- Renaming or restructuring the Schema Importer UI beyond correct tree data.

## Further notes

- Screenshot / repro: expand `catalog.schema.table_n` under a UC connection; previously showed sibling tables under the expanded table node.
- Related internal plan (optional): `.cursor/plans/fix_schema_importer_tree_*.plan.md` if present in the environment used for implementation.
