"""Authority Resolution — Policy references (ARF 1.2.0): reshape the policy table

Revision ID: an1_authority_policy_references
Revises: am1_authority_policies
Create Date: 2026-11-23

Additive on top of ``am1_authority_policies`` (which stays as it shipped on the
branch). The Authority Policy lifecycle becomes a plain reference: the source
document's name, external id, description, version and family, its validity
window, an optional link out and the owner team. Nothing about a reference is
enforced (#1294 decision).

Upgrade
- Adds ``url``, ``valid_from`` and ``valid_to``. The validity window is carried
  over from ``effective_from`` / ``effective_to`` for every row, whatever its
  status: a superseded or withdrawn reference keeps the dates it had.
- Drops the lifecycle and approval columns (``status``, ``approved_by``,
  ``approved_at``, ``approval_evidence_document_id``, ``withdrawn_reason``), the
  old window columns, ``policy_type`` and ``jurisdiction``, and the status index.
- Drops ``document_metadata.content_sha256``: nothing reads a policy document's
  hash any more. The document rows themselves stay (their files are still in the
  Volume and nothing deletes evidence on an upgrade).

Downgrade
- Restores the columns. Every reference becomes ``status = 'approved'`` with its
  window as the effective dates, ``approved_by`` = its creator and
  ``approved_at`` = its creation time (the approval is not recoverable from the
  reference; these values are the closest record). The hash column is restored
  empty.
"""
from typing import Any, Dict, Mapping, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'an1_authority_policy_references'
down_revision: Union[str, None] = 'am1_authority_policies'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LIFECYCLE_COLUMNS = (
    'status', 'approved_by', 'approved_at', 'approval_evidence_document_id', 'withdrawn_reason',
    'effective_from', 'effective_to', 'policy_type', 'jurisdiction',
)


def map_policy_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Upgrade: the reference fields one row keeps.

    The validity window is the only part of the old row that a reference carries.
    Status, approval and withdrawal are dropped, and the dates stay as they were
    whatever the status (a draft has none, and a superseded row keeps the end its
    successor set).
    """
    return {"valid_from": row["effective_from"], "valid_to": row["effective_to"]}


def restore_policy_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Downgrade: the old columns one reference row is restored with (see the module docstring)."""
    return {
        "status": "approved",
        "effective_from": row["valid_from"],
        "effective_to": row["valid_to"],
        "approved_by": row["created_by"],
        "approved_at": row["created_at"],
    }


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column('authority_policies', sa.Column('url', sa.String(), nullable=True))
    op.add_column('authority_policies', sa.Column('valid_from', sa.DateTime(timezone=True), nullable=True))
    op.add_column('authority_policies', sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True))

    rows = conn.execute(sa.text(
        "SELECT id, effective_from, effective_to FROM authority_policies"
    )).mappings().all()
    for row in rows:
        conn.execute(sa.text(
            "UPDATE authority_policies SET valid_from = :valid_from, valid_to = :valid_to WHERE id = :id"
        ), {"id": row["id"], **map_policy_row(row)})

    op.drop_index('ix_authority_policies_status', table_name='authority_policies')
    with op.batch_alter_table('authority_policies') as batch:
        for column in LIFECYCLE_COLUMNS:
            batch.drop_column(column)

    with op.batch_alter_table('document_metadata') as batch:
        batch.drop_column('content_sha256')


def downgrade() -> None:
    conn = op.get_bind()
    with op.batch_alter_table('document_metadata') as batch:
        batch.add_column(sa.Column('content_sha256', sa.String(length=64), nullable=True))

    with op.batch_alter_table('authority_policies') as batch:
        batch.add_column(sa.Column('status', sa.String(), nullable=False, server_default='approved'))
        batch.add_column(sa.Column('approved_by', sa.String(), nullable=True))
        batch.add_column(sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('approval_evidence_document_id', sa.String(), nullable=True))
        batch.add_column(sa.Column('withdrawn_reason', sa.Text(), nullable=True))
        batch.add_column(sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('policy_type', sa.String(), nullable=False, server_default='DOA'))
        batch.add_column(sa.Column('jurisdiction', sa.JSON(), nullable=True))

    rows = conn.execute(sa.text(
        "SELECT id, valid_from, valid_to, created_by, created_at FROM authority_policies"
    )).mappings().all()
    for row in rows:
        values = restore_policy_row(row)
        conn.execute(sa.text(
            "UPDATE authority_policies SET status = :status, effective_from = :effective_from, "
            "effective_to = :effective_to, approved_by = :approved_by, approved_at = :approved_at WHERE id = :id"
        ), {"id": row["id"], **values})

    op.create_index('ix_authority_policies_status', 'authority_policies', ['status'])
    with op.batch_alter_table('authority_policies') as batch:
        batch.drop_column('valid_to')
        batch.drop_column('valid_from')
        batch.drop_column('url')
