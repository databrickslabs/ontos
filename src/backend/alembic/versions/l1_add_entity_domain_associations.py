"""Add entity_domain_associations (multi-domain assignment) and drop legacy single-domain columns

Introduces the polymorphic ``entity_domain_associations`` junction table (multi-domain
assignment for teams, data contracts, data products and assets), backfills every existing
single-domain value as a *primary* association, then drops the four legacy scalar columns
(``teams.domain_id``, ``data_contracts.domain_id``, ``assets.domain_id``,
``data_products.domain``).

The data-product ``domain`` column is a free-text string that historically held either a
domain ID or a domain name; the backfill resolves ID first, then name, and logs any values
that cannot be resolved.

Revision ID: l1_entity_domain_associations
Revises: k1_merge_aa1_c1_g3
Create Date: 2026-07-06
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


revision: str = "l1_entity_domain_associations"
down_revision: Union[str, Sequence[str], None] = "k1_merge_aa1_c1_g3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

TABLE = "entity_domain_associations"


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
        {"n": name},
    ).scalar() is not None


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create the junction table (idempotent guard for partial re-runs).
    if not _table_exists(conn, TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
            sa.Column("domain_id", sa.String(), sa.ForeignKey("data_domains.id"), nullable=False),
            sa.Column("entity_id", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("assigned_by", sa.String(), nullable=True),
            sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        # Indexes mirror the ORM model (db_models/domain_associations.py).
        op.create_index(f"ix_{TABLE}_domain_id", TABLE, ["domain_id"])
        op.create_index(f"ix_{TABLE}_entity_id", TABLE, ["entity_id"])
        op.create_index(f"ix_{TABLE}_entity_type", TABLE, ["entity_type"])
        op.create_index(f"ix_{TABLE}_is_primary", TABLE, ["is_primary"])
        op.create_index("ix_entity_domain_entity", TABLE, ["entity_type", "entity_id"])
        op.create_unique_constraint(
            "uq_entity_domain_assignment", TABLE, ["domain_id", "entity_type", "entity_id"]
        )
        # At most one primary domain per entity.
        op.create_index(
            "uq_entity_domain_primary",
            TABLE,
            ["entity_type", "entity_id"],
            unique=True,
            postgresql_where=sa.text("is_primary"),
        )

    # 2. Backfill existing single-domain values as PRIMARY associations.
    #    Only rows whose domain resolves to a real data_domains.id are inserted
    #    (satisfies the FK and drops stale references).
    def _backfill_by_id(source_table: str, id_expr: str, domain_col: str, entity_type: str):
        conn.execute(sa.text(
            f"""
            INSERT INTO {TABLE} (id, domain_id, entity_id, entity_type, is_primary, assigned_by, assigned_at)
            SELECT gen_random_uuid(), s.{domain_col}, {id_expr}, :etype, TRUE, 'migration', now()
            FROM {source_table} s
            JOIN data_domains d ON d.id = s.{domain_col}
            WHERE s.{domain_col} IS NOT NULL
            ON CONFLICT ON CONSTRAINT uq_entity_domain_assignment DO NOTHING
            """
        ), {"etype": entity_type})

    _backfill_by_id("teams", "s.id", "domain_id", "team")
    _backfill_by_id("data_contracts", "s.id", "domain_id", "data_contract")
    _backfill_by_id("assets", "CAST(s.id AS VARCHAR)", "domain_id", "asset")

    # data_products.domain is free-text (ID or name). Resolve ID first, then name.
    # (a) domain value IS a domain id
    conn.execute(sa.text(
        f"""
        INSERT INTO {TABLE} (id, domain_id, entity_id, entity_type, is_primary, assigned_by, assigned_at)
        SELECT gen_random_uuid(), d.id, p.id, 'data_product', TRUE, 'migration', now()
        FROM data_products p
        JOIN data_domains d ON d.id = p.domain
        WHERE p.domain IS NOT NULL
        ON CONFLICT ON CONSTRAINT uq_entity_domain_assignment DO NOTHING
        """
    ))
    # (b) domain value is a domain NAME (and was not already resolved as an id)
    conn.execute(sa.text(
        f"""
        INSERT INTO {TABLE} (id, domain_id, entity_id, entity_type, is_primary, assigned_by, assigned_at)
        SELECT gen_random_uuid(), d.id, p.id, 'data_product', TRUE, 'migration', now()
        FROM data_products p
        JOIN data_domains d ON d.name = p.domain
        WHERE p.domain IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM data_domains d2 WHERE d2.id = p.domain)
        ON CONFLICT ON CONSTRAINT uq_entity_domain_assignment DO NOTHING
        """
    ))
    # (c) log unresolvable data-product domain values for manual reconciliation.
    unresolved = conn.execute(sa.text(
        """
        SELECT p.id, p.domain
        FROM data_products p
        WHERE p.domain IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM data_domains d WHERE d.id = p.domain)
          AND NOT EXISTS (SELECT 1 FROM data_domains d WHERE d.name = p.domain)
        """
    )).fetchall()
    for row in unresolved:
        logger.warning(
            "Multi-domain migration: could not resolve data_product %s domain value %r; dropped.",
            row[0], row[1],
        )

    # 3. Drop the four legacy scalar columns (Postgres cascades FK/index cleanup).
    if _column_exists(conn, "teams", "domain_id"):
        op.drop_column("teams", "domain_id")
    if _column_exists(conn, "data_contracts", "domain_id"):
        op.drop_column("data_contracts", "domain_id")
    if _column_exists(conn, "assets", "domain_id"):
        op.drop_column("assets", "domain_id")
    if _column_exists(conn, "data_products", "domain"):
        op.drop_column("data_products", "domain")


def downgrade() -> None:
    conn = op.get_bind()

    # 1. Re-add the legacy columns (nullable).
    if not _column_exists(conn, "teams", "domain_id"):
        op.add_column("teams", sa.Column("domain_id", sa.String(), sa.ForeignKey("data_domains.id"), nullable=True))
    if not _column_exists(conn, "data_contracts", "domain_id"):
        op.add_column("data_contracts", sa.Column("domain_id", sa.String(), sa.ForeignKey("data_domains.id"), nullable=True))
    if not _column_exists(conn, "assets", "domain_id"):
        op.add_column("assets", sa.Column("domain_id", sa.String(), nullable=True))
    if not _column_exists(conn, "data_products", "domain"):
        op.add_column("data_products", sa.Column("domain", sa.String(), nullable=True))

    # 2. Restore the primary domain into each legacy column.
    conn.execute(sa.text(
        f"""
        UPDATE teams t SET domain_id = a.domain_id
        FROM {TABLE} a
        WHERE a.entity_type = 'team' AND a.entity_id = t.id AND a.is_primary = TRUE
        """
    ))
    conn.execute(sa.text(
        f"""
        UPDATE data_contracts c SET domain_id = a.domain_id
        FROM {TABLE} a
        WHERE a.entity_type = 'data_contract' AND a.entity_id = c.id AND a.is_primary = TRUE
        """
    ))
    conn.execute(sa.text(
        f"""
        UPDATE assets s SET domain_id = a.domain_id
        FROM {TABLE} a
        WHERE a.entity_type = 'asset' AND a.entity_id = CAST(s.id AS VARCHAR) AND a.is_primary = TRUE
        """
    ))
    conn.execute(sa.text(
        f"""
        UPDATE data_products p SET domain = a.domain_id
        FROM {TABLE} a
        WHERE a.entity_type = 'data_product' AND a.entity_id = p.id AND a.is_primary = TRUE
        """
    ))

    # 3. Drop the junction table.
    if _table_exists(conn, TABLE):
        op.drop_table(TABLE)
