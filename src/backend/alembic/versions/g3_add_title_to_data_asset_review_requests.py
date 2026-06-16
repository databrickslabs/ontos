"""add title column to data_asset_review_requests with backfill

Revision ID: g3_review_title
Revises: g2_ontology_gen_runs
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g3_review_title"
down_revision: Union[str, None] = "g2_ontology_gen_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _short_name(fqn: str) -> str:
    """Return a compact human-readable label for an asset FQN.

    Mirrors the runtime helper in src/controller/data_asset_reviews_manager.py
    so backfilled titles match what the manager would produce.
    """
    if not fqn:
        return "asset"
    if fqn.startswith("mdm://"):
        tail = fqn[len("mdm://"):].rstrip("/")
        last = tail.rsplit("/", 1)[-1] if tail else ""
        return last or "MDM match"
    if "/" in fqn:
        last = fqn.rstrip("/").rsplit("/", 1)[-1]
        return last or fqn
    return fqn.split(".")[-1] or fqn


def upgrade() -> None:
    op.add_column(
        "data_asset_review_requests",
        sa.Column("title", sa.String(length=200), nullable=True),
    )

    bind = op.get_bind()

    rows = bind.execute(
        sa.text(
            "SELECT id, requester_email FROM data_asset_review_requests "
            "WHERE title IS NULL OR title = ''"
        )
    ).fetchall()

    for row in rows:
        request_id = row[0]
        requester_email = row[1] or ""

        asset_rows = bind.execute(
            sa.text(
                "SELECT asset_fqn FROM reviewed_assets "
                "WHERE review_request_id = :rid"
            ),
            {"rid": request_id},
        ).fetchall()

        asset_count = len(asset_rows)
        if asset_count == 1:
            title = f"Review of {_short_name(asset_rows[0][0])}"
        elif asset_count > 1:
            title = f"Review of {_short_name(asset_rows[0][0])} (+{asset_count - 1} more)"
        else:
            title = f"Review request by {requester_email}" if requester_email else "Review request"

        title = title[:200]

        bind.execute(
            sa.text(
                "UPDATE data_asset_review_requests SET title = :title WHERE id = :rid"
            ),
            {"title": title, "rid": request_id},
        )


def downgrade() -> None:
    op.drop_column("data_asset_review_requests", "title")
