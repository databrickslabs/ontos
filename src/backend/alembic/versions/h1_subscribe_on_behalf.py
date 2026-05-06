"""Subscribe on behalf of group/SP + consumer_principals metadata.

Adds:
- ``data_products.consumer_principals`` (TEXT, JSON-encoded list of typed
  principals: ``[{type: "group"|..., value: "..."}, ...]``).
  Surfaced in publish form + exposed to webhook bodies via
  ``${entity.consumer_principals}``. Default ``type="group"``; the shape is
  intentionally extensible to non-group identity methods (service principals,
  IdP roles, OAuth scopes) without a future breaking migration.
- ``data_product_subscriptions.on_behalf_of_type`` (VARCHAR(50))
- ``data_product_subscriptions.on_behalf_of_value`` (VARCHAR(255))
  Capture which group / SP / user the subscription was requested for when it
  differs from the subscriber.

Idempotent (``ADD COLUMN IF NOT EXISTS``) so partial deploys are safe.

Revision ID: h1_subscribe_on_behalf
Revises: g1_workflow_snapshot
Create Date: 2026-05-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h1_subscribe_on_behalf"
down_revision: Union[str, Sequence[str], None] = "g1_workflow_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # data_products.consumer_principals (JSON-encoded list of {type, value}
    # principals). Stored as TEXT for portability across SQLite (dev) and
    # Postgres (prod); backend serializes to JSON via Pydantic + a parse hook
    # in the repository.
    op.execute(
        "ALTER TABLE data_products "
        "ADD COLUMN IF NOT EXISTS consumer_principals TEXT"
    )

    # data_product_subscriptions: subscribe-on-behalf-of metadata.
    op.execute(
        "ALTER TABLE data_product_subscriptions "
        "ADD COLUMN IF NOT EXISTS on_behalf_of_type VARCHAR(50)"
    )
    op.execute(
        "ALTER TABLE data_product_subscriptions "
        "ADD COLUMN IF NOT EXISTS on_behalf_of_value VARCHAR(255)"
    )


def downgrade() -> None:
    op.drop_column("data_product_subscriptions", "on_behalf_of_value")
    op.drop_column("data_product_subscriptions", "on_behalf_of_type")
    op.drop_column("data_products", "consumer_principals")
