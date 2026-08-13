"""Record each re-upload as an ``upload_event`` (upload history + rollback, P2-1).

A re-upload is a bulk versioning event (see ``apply_upload_as_versioning_event``).
To make an upload roll-back-able we persist, for every upload, a small
append-only row capturing:
  - the diff ``summary`` (counts) for the event, and
  - the per-concept BEFORE-state (``concept_prev_state``): for each concept the
    upload touched, what version/status it was AT before this event.

Rollback is FORWARD, never a delete: it re-applies those prior states as a NEW
bulk versioning event (itself an ``upload_event``, itself roll-back-able). We do
NOT snapshot full triples here — the ``concept_version`` rows already hold the
frozen per-version triples; ``concept_prev_state`` only stores the POINTER
(``prev_version``) to which version was current before, plus ``prev_status`` and
the ``bucket`` (modified/new/removed) the concept fell into.

Revision ID: m5_upload_event
Revises: m4_rdf_triple_version_uq
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import JSON


revision: str = 'm5_upload_event'
down_revision: Union[str, None] = 'm4_rdf_triple_version_uq'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'upload_event',
        sa.Column('id', PG_UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        # The file/model context this upload targeted.
        sa.Column('context_name', sa.Text(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        # Diff summary counts for the event: {unchanged, modified, new, removed}.
        sa.Column('summary', JSON, nullable=True),
        # Per-concept before-state list:
        #   [{iri, prev_version|null, prev_status|null, bucket}, ...]
        sa.Column('concept_prev_state', JSON, nullable=True),
    )
    op.create_index('ix_upload_event_context_name', 'upload_event',
                    ['context_name'])
    op.create_index('ix_upload_event_created_at', 'upload_event',
                    ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_upload_event_created_at', table_name='upload_event')
    op.drop_index('ix_upload_event_context_name', table_name='upload_event')
    op.drop_table('upload_event')
