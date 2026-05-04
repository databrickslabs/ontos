"""Daimler go-live: thread on_behalf_of through wizard auto-subscribe.

Adds:
- ``agreement_wizard_sessions.on_behalf_of_type`` (VARCHAR(50))
- ``agreement_wizard_sessions.on_behalf_of_value`` (VARCHAR(255))

Captures the on_behalf_of principal at wizard start so the auto-subscribe
fired in ``_complete_session`` (when ``completion_action='subscribe'``) can
forward it to ``data_products_manager.subscribe()``. Without this, end-users
going through the approval wizard ended up with subscriptions where
``on_behalf_of_type=NULL`` even though they selected a group up front.

Daimler CSV #486363 — gap-fill on top of ``h1_daimler_subscribe_on_behalf``.

Idempotent (``ADD COLUMN IF NOT EXISTS``) so partial deploys are safe.

Revision ID: h2_wizard_obo
Revises: h1_daimler_subscribe_on_behalf
Create Date: 2026-05-01
"""
from typing import Sequence, Union

from alembic import op


revision: str = "h2_wizard_obo"
down_revision: Union[str, Sequence[str], None] = "h1_daimler_subscribe_on_behalf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agreement_wizard_sessions "
        "ADD COLUMN IF NOT EXISTS on_behalf_of_type VARCHAR(50)"
    )
    op.execute(
        "ALTER TABLE agreement_wizard_sessions "
        "ADD COLUMN IF NOT EXISTS on_behalf_of_value VARCHAR(255)"
    )


def downgrade() -> None:
    op.drop_column("agreement_wizard_sessions", "on_behalf_of_value")
    op.drop_column("agreement_wizard_sessions", "on_behalf_of_type")
