"""Rename consumer_groups → consumer_principals; migrate shape to typed principals.

Pre-merge schema rename agreed with reviewer. Changes the consumer metadata
column name and JSON shape from a flat list of group display names to a typed
list of {type, value} principals (default type="group"). This makes the model
honest about supporting non-group identity methods (service principals, IdP
roles, OAuth scopes) without a future breaking migration.

Idempotent — guards both the rename (only if old column exists and new doesn't)
and the data shape migration (only rewrites rows that still have string-array
shape).

Revision ID: h3_rename_consumer_principals
Revises: h2_wizard_obo
Create Date: 2026-05-06
"""
from typing import Sequence, Union

from alembic import op


revision: str = "h3_rename_consumer_principals"
down_revision: Union[str, Sequence[str], None] = "h2_wizard_obo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Conditional column rename. Postgres-only DO block; SQLite dev DBs are
    # typically reset or already on the new shape so this guard is for prod.
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_products' AND column_name = 'consumer_groups'
      )
      AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_products' AND column_name = 'consumer_principals'
      ) THEN
        ALTER TABLE data_products RENAME COLUMN consumer_groups TO consumer_principals;
      END IF;
    END $$;
    """)

    # 2) Data shape migration: convert ["x","y"] -> [{"type":"group","value":"x"},...]
    # Only rewrites rows where the JSON array's first element is still a string
    # (i.e. old shape). Idempotent — re-run is a no-op once shape is converted.
    op.execute("""
    UPDATE data_products
    SET consumer_principals = (
      SELECT json_agg(json_build_object('type', 'group', 'value', x))::text
      FROM json_array_elements_text(consumer_principals::json) AS x
    )
    WHERE consumer_principals IS NOT NULL
      AND consumer_principals != ''
      AND consumer_principals != '[]'
      AND json_typeof(consumer_principals::json) = 'array'
      AND json_array_length(consumer_principals::json) > 0
      AND json_typeof((consumer_principals::json)->0) = 'string';
    """)


def downgrade() -> None:
    # Reverse data shape: extract value from each principal object back to a flat string
    op.execute("""
    UPDATE data_products
    SET consumer_principals = (
      SELECT json_agg(elem->>'value')::text
      FROM json_array_elements(consumer_principals::json) AS elem
    )
    WHERE consumer_principals IS NOT NULL
      AND consumer_principals != ''
      AND consumer_principals != '[]'
      AND json_typeof(consumer_principals::json) = 'array'
      AND json_array_length(consumer_principals::json) > 0
      AND json_typeof((consumer_principals::json)->0) = 'object';
    """)

    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_products' AND column_name = 'consumer_principals'
      )
      AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_products' AND column_name = 'consumer_groups'
      ) THEN
        ALTER TABLE data_products RENAME COLUMN consumer_principals TO consumer_groups;
      END IF;
    END $$;
    """)
