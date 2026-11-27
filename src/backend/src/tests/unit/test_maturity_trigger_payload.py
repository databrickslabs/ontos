"""What ``on_maturity_change`` puts in a workflow's payload.

An asset's levels can come from another user's Unity Catalog read. The payload
is stored on the execution and shown to approvers (``full_payload``), so an
asset's payload carries no ``from_maturity_level`` / ``to_maturity_level``;
products and contracts keep them.
"""
import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.common.workflow_triggers import TriggerRegistry
from src.db_models.notifications import NotificationDb
from src.db_models.process_workflows import (
    ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb,
)
from src.models.process_workflows import EntityType

LEVEL_KEYS = ('from_maturity_level', 'to_maturity_level')
ASSET_DATA = {
    'asset_id': 'a1', 'asset_type': 'Table', 'location': 'main.sales.orders',
    'uc_table_name': 'main.sales.orders',
}
ASSET_TYPES = [EntityType.TABLE, EntityType.VIEW, EntityType.METRIC_VIEW]


def _fired(entity_type, entity_data):
    registry = TriggerRegistry(MagicMock())
    registry.fire_trigger = MagicMock(return_value=[])
    registry.on_maturity_change(
        entity_type=entity_type, entity_id='e1', entity_data=entity_data,
        from_level=1, to_level=2,
    )
    return registry.fire_trigger.call_args[0][0]


@pytest.mark.parametrize('entity_type', ASSET_TYPES)
def test_an_asset_payload_has_no_level(entity_type):
    event = _fired(entity_type, dict(ASSET_DATA))

    assert event.entity_data == ASSET_DATA


def test_an_asset_payload_drops_levels_its_caller_passed():
    event = _fired(EntityType.TABLE, {**ASSET_DATA, 'to_maturity_level': 2})

    assert not set(LEVEL_KEYS) & set(event.entity_data)


@pytest.mark.parametrize('entity_type', [EntityType.DATA_PRODUCT, EntityType.DATA_CONTRACT])
def test_a_product_or_contract_payload_keeps_its_levels(entity_type):
    event = _fired(entity_type, None)

    assert event.entity_data == {'from_maturity_level': 1, 'to_maturity_level': 2}


def _approval_workflow(db, entity_type):
    now = datetime.utcnow()
    wf_id = str(uuid.uuid4())
    db.add(ProcessWorkflowDb(
        id=wf_id, name=f'Maturity {entity_type}', description='approve a level change',
        trigger_config=json.dumps({'type': 'on_maturity_change', 'entity_types': [entity_type]}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        workflow_type='process', created_at=now, updated_at=now,
    ))
    db.flush()
    db.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='approve', name='Approve',
        step_type='approval', config=json.dumps({'approvers': 'approver@example.com'}),
        on_pass='ok', order=0, created_at=now, updated_at=now,
    ))
    db.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='ok', name='Ok', step_type='pass',
        config='{}', order=1, created_at=now, updated_at=now,
    ))
    db.flush()
    return wf_id


def _stored_payloads(db, wf_id):
    """The execution's stored trigger data and the approval's ``full_payload``."""
    execution = db.query(WorkflowExecutionDb).filter_by(workflow_id=wf_id).one()
    notification = db.query(NotificationDb).filter(
        NotificationDb.action_type == 'workflow_approval',
        NotificationDb.action_payload.contains(execution.id),
    ).one()
    stored = json.loads(execution.trigger_context)['entity_data']
    return stored, json.loads(notification.action_payload)['full_payload']


def test_an_asset_level_reaches_neither_the_execution_nor_the_approver(db_session):
    wf_id = _approval_workflow(db_session, 'table')

    TriggerRegistry(db_session).on_maturity_change(
        entity_type=EntityType.TABLE, entity_id='main.sales.orders',
        entity_name='orders', entity_data=dict(ASSET_DATA), from_level=1, to_level=2,
        user_email='owner@example.com', blocking=True,
    )

    stored, full_payload = _stored_payloads(db_session, wf_id)
    for payload in (stored, full_payload):
        assert payload['uc_table_name'] == 'main.sales.orders'
        assert not set(LEVEL_KEYS) & set(payload)


def test_a_product_level_reaches_the_execution_and_the_approver(db_session):
    wf_id = _approval_workflow(db_session, 'data_product')

    TriggerRegistry(db_session).on_maturity_change(
        entity_type=EntityType.DATA_PRODUCT, entity_id=str(uuid.uuid4()),
        entity_name='Sales', from_level=1, to_level=2,
        user_email='owner@example.com', blocking=True,
    )

    stored, full_payload = _stored_payloads(db_session, wf_id)
    for payload in (stored, full_payload):
        assert payload['from_maturity_level'] == 1
        assert payload['to_maturity_level'] == 2
