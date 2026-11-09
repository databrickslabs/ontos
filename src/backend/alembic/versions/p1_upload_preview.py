"""Add upload_preview table (P1-0: steward preview + confirm on re-upload).

A file re-upload no longer auto-applies its diff. The manager stashes the
incoming file content in this table keyed by an opaque token; the steward is
shown a preview and NOTHING is applied until ``confirm_upload(token)`` re-parses
the stash and runs the existing versioning-event primitive, then deletes the
row. Single-use stash.

Revision ID: p1_upload_preview
Revises: m4_rdf_triple_version_uq
Create Date: 2026-08-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


revision: str = 'p1_upload_preview'
down_revision: Union[str, None] = 'm4_rdf_triple_version_uq'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'upload_preview',
        sa.Column('token', PG_UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('context_name', sa.Text(), nullable=False),
        sa.Column('content_text', sa.Text(), nullable=False),
        sa.Column('format', sa.String(length=20), nullable=False, server_default='skos'),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table('upload_preview')
