"""Add version_family_id to data_contracts and data_products.

Introduces a single canonical, immutable grouping key per version family so
"list all versions of family X" becomes one indexed equality lookup and no
longer relies on the mutable / inconsistently-populated `name` / `base_name`
heuristics that `get_contract_versions` currently falls back to.

`parent_contract_id` / `parent_product_id` continue to encode lineage (one
edge per row to the predecessor); `version_family_id` is the denormalized
set-membership tag carrying the root's id on every member of the family.

Backfill walks the parent chain via a recursive CTE and assigns each row
the root's id. Rows whose parent chain doesn't reach a root (orphans) are
treated as their own root (defensive).

See PRD: docs/prds/prd-version-family-and-unified-selector.md
See GH:  https://github.com/databrickslabs/ontos/issues/442

Revision ID: j1_add_version_family_id
Revises: i1_workflow_version
Create Date: 2026-05-27
"""
from typing import Sequence, Union

from alembic import op


revision: str = "j1_add_version_family_id"
down_revision: Union[str, Sequence[str], None] = "i1_workflow_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add the column (nullable for now; tightened to NOT NULL after backfill).
    op.execute(
        "ALTER TABLE data_contracts ADD COLUMN IF NOT EXISTS version_family_id VARCHAR"
    )
    op.execute(
        "ALTER TABLE data_products ADD COLUMN IF NOT EXISTS version_family_id VARCHAR"
    )

    # 2. Indexes for "all rows in this family" lookups.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_data_contracts_version_family_id "
        "ON data_contracts (version_family_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_data_products_version_family_id "
        "ON data_products (version_family_id)"
    )

    # 3. Backfill via recursive CTE.
    # roots = anchor (parent IS NULL); recursion adds each child carrying the
    # root's id. Orphans (broken chain) fall through the COALESCE and get
    # themselves as family root.
    op.execute("""
        WITH RECURSIVE roots AS (
            SELECT id, id AS root_id
            FROM data_contracts
            WHERE parent_contract_id IS NULL
            UNION ALL
            SELECT c.id, r.root_id
            FROM data_contracts c
            JOIN roots r ON c.parent_contract_id = r.id
        )
        UPDATE data_contracts dc
        SET version_family_id = COALESCE(
            (SELECT r.root_id FROM roots r WHERE r.id = dc.id),
            dc.id
        )
        WHERE dc.version_family_id IS NULL;
    """)

    op.execute("""
        WITH RECURSIVE roots AS (
            SELECT id, id AS root_id
            FROM data_products
            WHERE parent_product_id IS NULL
            UNION ALL
            SELECT p.id, r.root_id
            FROM data_products p
            JOIN roots r ON p.parent_product_id = r.id
        )
        UPDATE data_products dp
        SET version_family_id = COALESCE(
            (SELECT r.root_id FROM roots r WHERE r.id = dp.id),
            dp.id
        )
        WHERE dp.version_family_id IS NULL;
    """)

    # 4. Tighten to NOT NULL now that every row has a value.
    op.execute(
        "ALTER TABLE data_contracts ALTER COLUMN version_family_id SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE data_products ALTER COLUMN version_family_id SET NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_data_contracts_version_family_id"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_data_products_version_family_id"
    )
    op.execute(
        "ALTER TABLE data_contracts DROP COLUMN IF EXISTS version_family_id"
    )
    op.execute(
        "ALTER TABLE data_products DROP COLUMN IF EXISTS version_family_id"
    )
