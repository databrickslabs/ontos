"""Add notification_recipients and the policy rule author

Revision ID: s3_notification_recipients
Revises: r2_canonical_relationship_types
Create Date: 2026-11-12

Notification Recipients (#1450): named NOTIFY targets an admin defines in Settings,
with an allow-list of app roles. Compliance policies record who last changed their
rule (and that user's groups), so NOTIFY recipients can be checked against the
author's roles at save and at run time.

Existing policies get no author; their NOTIFY targets other than the entity's
owners are refused until an admin saves them again.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 's3_notification_recipients'
down_revision: Union[str, None] = 'r2_canonical_relationship_types'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'notification_recipients' not in inspector.get_table_names():
        op.create_table(
            'notification_recipients',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False, unique=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('targets', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('allowed_role_ids', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('created_by', sa.String(), nullable=True),
            sa.Column('updated_by', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        )

    recipient_indexes = {i['name'] for i in inspector.get_indexes('notification_recipients')} \
        if 'notification_recipients' in inspector.get_table_names() else set()
    if 'uq_notification_recipients_name_ci' not in recipient_indexes:
        op.create_index(
            'uq_notification_recipients_name_ci', 'notification_recipients', [sa.text('lower(name)')], unique=True,
        )

    policy_columns = {c['name'] for c in inspector.get_columns('compliance_policies')}
    if 'rule_author_email' not in policy_columns:
        op.add_column('compliance_policies', sa.Column('rule_author_email', sa.String(), nullable=True))
    if 'rule_author_groups' not in policy_columns:
        op.add_column('compliance_policies', sa.Column('rule_author_groups', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_index('uq_notification_recipients_name_ci', table_name='notification_recipients')
    op.drop_column('compliance_policies', 'rule_author_groups')
    op.drop_column('compliance_policies', 'rule_author_email')
    op.drop_table('notification_recipients')
