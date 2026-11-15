"""Add the source of imported Markdown documents and their text, once per file

Revision ID: s2_document_markdown_import
Revises: o2_step_execution_message
Create Date: 2026-11-12

Markdown files imported from a Unity Catalog volume become documents on the
entities their front matter names. On document_metadata, ``source_path`` is
the file they came from and ``content_hash`` (SHA-256 of the file) tells a
re-run whether the file changed; uploaded documents leave both empty. The new
table imported_markdown_files keeps the Markdown once per file (not once per
entity), so search can index it and the documents open without reading the
source volume again. A partial unique index on (source_path, entity_type,
entity_id) keeps one imported document per file and entity, also when two
imports overlap.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 's2_document_markdown_import'
down_revision: Union[str, None] = 'o2_step_execution_message'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('document_metadata', sa.Column('source_path', sa.String(), nullable=True))
    op.add_column('document_metadata',
                  sa.Column('content_hash', sa.String(length=64), nullable=True))
    op.create_table(
        'imported_markdown_files',
        sa.Column('source_path', sa.String(), primary_key=True),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('content_text', sa.Text(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index(
        'uq_document_imported_target', 'document_metadata',
        ['source_path', 'entity_type', 'entity_id'], unique=True,
        postgresql_where=sa.text('source_path IS NOT NULL'),
        sqlite_where=sa.text('source_path IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_document_imported_target', table_name='document_metadata')
    op.drop_table('imported_markdown_files')
    op.drop_column('document_metadata', 'content_hash')
    op.drop_column('document_metadata', 'source_path')
