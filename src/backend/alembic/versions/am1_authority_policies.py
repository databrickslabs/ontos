"""Authority Resolution — Authority Policy (justification basis)

Revision ID: am1_authority_policies
Revises: al1_authority_scoped_context
Create Date: 2026-11-12

Creates ``authority_policies`` (versioned policy basis with clauses), lets an
AR cite a policy version and its clauses (``authority_relations.authority_policy_id`` /
``policy_clause_refs``) and a check cite the clause it enforces
(``authority_criteria.policy_clause_ref``), and stores the SHA-256 of uploaded
Metadata documents (``document_metadata.content_sha256``). Existing ARs cite
no policy, so nothing changes for them; the legacy ``justification_chain``
blob stays readable.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'am1_authority_policies'
down_revision: Union[str, None] = 'al1_authority_scoped_context'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'authority_policies',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('policy_key', sa.String(), nullable=False),
        sa.Column('version', sa.String(), nullable=False, server_default='1'),
        sa.Column('version_family_id', sa.String(), nullable=True),
        sa.Column('parent_policy_id', sa.String(), nullable=True),
        sa.Column('change_summary', sa.Text(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('policy_type', sa.String(), nullable=False, server_default='DOA'),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('owner_team_id', sa.String(), sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('jurisdiction', sa.JSON(), nullable=True),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='draft'),
        sa.Column('approved_by', sa.String(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approval_evidence_document_id', sa.String(), nullable=True),
        sa.Column('withdrawn_reason', sa.Text(), nullable=True),
        sa.Column('clauses', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_authority_policies_policy_key', 'authority_policies', ['policy_key'])
    op.create_index('ix_authority_policies_version_family_id', 'authority_policies', ['version_family_id'])
    op.create_index('ix_authority_policies_parent_policy_id', 'authority_policies', ['parent_policy_id'])
    op.create_index('ix_authority_policies_owner_team_id', 'authority_policies', ['owner_team_id'])
    op.create_index('ix_authority_policies_status', 'authority_policies', ['status'])

    op.add_column('authority_relations', sa.Column('authority_policy_id', sa.String(), nullable=True))
    op.add_column('authority_relations', sa.Column('policy_clause_refs', sa.JSON(), nullable=True))
    op.create_foreign_key(
        'fk_authority_relations_authority_policy_id', 'authority_relations', 'authority_policies',
        ['authority_policy_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_authority_relations_authority_policy_id', 'authority_relations', ['authority_policy_id'])

    op.add_column('authority_criteria', sa.Column('policy_clause_ref', sa.String(), nullable=True))
    op.add_column('document_metadata', sa.Column('content_sha256', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('document_metadata', 'content_sha256')
    op.drop_column('authority_criteria', 'policy_clause_ref')
    # Dropping the column drops its FK and index too (whatever they were named:
    # a create_all-provisioned schema uses the dialect's default FK name).
    op.drop_column('authority_relations', 'policy_clause_refs')
    op.drop_column('authority_relations', 'authority_policy_id')
    op.drop_table('authority_policies')  # its indexes go with it
