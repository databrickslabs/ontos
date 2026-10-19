"""Turn the default 'Data Contract Publish Request' into 'Data Contract Deploy Request'

Contract deploy requests now fire their own trigger (on_request_deploy), and
the default workflow that handled them was renamed and moved to it in
default_workflows.yaml. Installs that loaded the defaults before keep the old
row, which still listens to on_request_publish, and startup seeding only
creates missing workflows.

This migration updates that row in place, only while it is still the shipped
default: is_default, the old name, the on_request_publish trigger, and no
'Data Contract Deploy Request' yet. Within it, each text (description, step
names, messages) is replaced only if it still has the shipped value, so admin
edits are kept.

Revision ID: b2_contract_deploy_default
Revises: b1_add_adopt_entity_ids
Create Date: 2026-10-15
"""
import json

import sqlalchemy as sa
from alembic import op

revision = 'b2_contract_deploy_default'
down_revision = 'b1_add_adopt_entity_ids'
branch_labels = None
depends_on = None

OLD_NAME = 'Data Contract Publish Request'
NEW_NAME = 'Data Contract Deploy Request'
OLD_TRIGGER = 'on_request_publish'
NEW_TRIGGER = 'on_request_deploy'
OLD_DESCRIPTION = (
    'Handles requests to publish data contracts to the marketplace with approver authorization.'
)
NEW_DESCRIPTION = (
    'Handles requests to deploy data contracts to Unity Catalog with approver authorization.'
)

# step_id -> ((old name, old config), (new name, new config)); None: no config
STEPS = {
    'notify-requester': (
        ('Confirm Publish Request Received', {
            'recipients': 'requester', 'template': 'request_submitted',
            'custom_message': 'Your request to publish the data contract to the marketplace '
                              'has been submitted.',
        }),
        ('Confirm Deploy Request Received', {
            'recipients': 'requester', 'template': 'request_submitted',
            'custom_message': "Your request to deploy the data contract '${entity_name}' "
                              'to Unity Catalog has been submitted.',
        }),
    ),
    'notify-approved': (
        ('Notify Publish Approved', {
            'recipients': 'requester', 'template': 'request_approved',
            'custom_message': 'Your data contract has been approved for publishing to the '
                              'marketplace.',
        }),
        ('Notify Deploy Approved', {
            'recipients': 'requester', 'template': 'request_approved',
            'custom_message': "Your request to deploy the data contract '${entity_name}' "
                              'has been approved.',
        }),
    ),
    'notify-rejected': (
        ('Notify Publish Rejected', {
            'recipients': 'requester', 'template': 'request_rejected',
            'custom_message': 'Your publish request has been denied. Please review the feedback.',
        }),
        ('Notify Deploy Rejected', {
            'recipients': 'requester', 'template': 'request_rejected',
            'custom_message': "Your request to deploy the data contract '${entity_name}' "
                              'has been denied. Please review the feedback.',
        }),
    ),
    'success': (('Publish Approved', None), ('Deploy Approved', None)),
    'fail-rejected': (
        ('Publish Rejected', {'message': 'Data contract publish request was rejected'}),
        ('Deploy Rejected', {'message': 'Data contract deploy request was rejected'}),
    ),
}


def _parse(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return text


def _convert(from_name, from_trigger, from_description, to_name, to_trigger, to_description,
             step_index_from, step_index_to):
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT 1 FROM process_workflows WHERE name = :name"), {'name': to_name}
    ).first():
        return
    row = bind.execute(
        sa.text(
            "SELECT id, description, trigger_config FROM process_workflows "
            "WHERE name = :name AND is_default"
        ),
        {'name': from_name},
    ).first()
    if not row:
        return
    trigger = _parse(row.trigger_config)
    if not isinstance(trigger, dict) or trigger.get('type') != from_trigger:
        return

    trigger['type'] = to_trigger
    values = {'id': row.id, 'name': to_name, 'trigger': json.dumps(trigger)}
    description_sql = ''
    if row.description == from_description:
        description_sql = ', description = :description'
        values['description'] = to_description
    bind.execute(
        sa.text(
            "UPDATE process_workflows SET name = :name, trigger_config = :trigger"
            f"{description_sql} WHERE id = :id"
        ),
        values,
    )

    for step_id, versions in STEPS.items():
        old_name, old_config = versions[step_index_from]
        new_name, new_config = versions[step_index_to]
        step = bind.execute(
            sa.text(
                "SELECT id, name, config FROM workflow_steps "
                "WHERE workflow_id = :wf AND step_id = :step"
            ),
            {'wf': row.id, 'step': step_id},
        ).first()
        if not step:
            continue
        if step.name == old_name:
            bind.execute(
                sa.text("UPDATE workflow_steps SET name = :name WHERE id = :id"),
                {'name': new_name, 'id': step.id},
            )
        if old_config is not None and _parse(step.config) == old_config:
            bind.execute(
                sa.text("UPDATE workflow_steps SET config = :config WHERE id = :id"),
                {'config': json.dumps(new_config), 'id': step.id},
            )


def upgrade() -> None:
    _convert(OLD_NAME, OLD_TRIGGER, OLD_DESCRIPTION, NEW_NAME, NEW_TRIGGER, NEW_DESCRIPTION, 0, 1)


def downgrade() -> None:
    _convert(NEW_NAME, NEW_TRIGGER, NEW_DESCRIPTION, OLD_NAME, OLD_TRIGGER, OLD_DESCRIPTION, 1, 0)
