"""Activation warning for overlapping workflows (#964)."""
import json
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import ProcessWorkflowDb
from src.models.process_workflows import (
    ProcessWorkflowCreate, ProcessWorkflowUpdate, WorkflowScope, WorkflowStepCreate, WorkflowTrigger,
)
from src.routes.workflows_routes import create_workflow, toggle_workflow_active, update_workflow


def _workflow(db, name, *, active, trigger='on_request_review', entities=None,
              scope_type='all', scope_ids=None, from_status=None, to_status=None):
    row = ProcessWorkflowDb(
        id=str(uuid4()), name=name, is_active=active, workflow_type='process',
        trigger_config=json.dumps({
            'type': trigger, 'entity_types': entities or [],
            'from_status': from_status, 'to_status': to_status,
        }),
        scope_config=json.dumps({'type': scope_type, 'ids': scope_ids or []}),
    )
    db.add(row)
    db.commit()
    return row


def test_duplicate_review_workflow_is_reported(db_session):
    active = _workflow(db_session, 'Data Contract Review', active=True,
                       entities=['data_contract'])
    copy = _workflow(db_session, 'Data Contract Review Copy', active=False,
                     entities=['data_contract'])

    assert WorkflowsManager(db_session).activation_conflicts(copy.id) == [{
        'id': active.id,
        'name': active.name,
        'trigger_type': 'on_request_review',
        'entity_types': ['data_contract'],
        'scope_type': 'all',
    }]


def test_distinct_entity_status_and_scope_do_not_conflict(db_session):
    _workflow(db_session, 'Product review', active=True, entities=['data_product'])
    _workflow(db_session, 'Other transition', active=True, trigger='on_status_change',
              entities=['data_contract'], from_status='draft', to_status='active')
    _workflow(db_session, 'Other domain', active=True, entities=['data_contract'],
              scope_type='domain', scope_ids=['domain-b'])
    target = _workflow(db_session, 'Target', active=False, entities=['data_contract'],
                       scope_type='domain', scope_ids=['domain-a'])

    assert WorkflowsManager(db_session).activation_conflicts(target.id) == []


def test_empty_entity_list_is_a_wildcard(db_session):
    active = _workflow(db_session, 'All entities', active=True, entities=[])
    target = _workflow(db_session, 'Contract review', active=False,
                       entities=['data_contract'])

    conflicts = WorkflowsManager(db_session).activation_conflicts(target.id)
    assert [item['id'] for item in conflicts] == [active.id]


def _toggle(db_session, target, audit, *, confirm=False):
    return asyncio.run(toggle_workflow_active(
        request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')),
        workflow_id=target.id,
        db=db_session,
        audit_manager=audit,
        current_user=SimpleNamespace(email='admin@example.com', username='admin'),
        is_active=True,
        confirm_overlap=confirm,
        manager=WorkflowsManager(db_session),
        _=True,
    ))


def test_route_refuses_unconfirmed_overlap(db_session):
    _workflow(db_session, 'Active review', active=True, entities=['data_contract'])
    target = _workflow(db_session, 'Review copy', active=False,
                       entities=['data_contract'])

    with pytest.raises(HTTPException) as raised:
        _toggle(db_session, target, MagicMock())

    assert raised.value.status_code == 409
    assert raised.value.detail['code'] == 'workflow_activation_overlap'
    assert raised.value.detail['conflicts'][0]['name'] == 'Active review'
    assert db_session.get(ProcessWorkflowDb, target.id).is_active is False


def test_route_activates_after_confirmation_and_audits_conflict(db_session):
    active = _workflow(db_session, 'Active review', active=True,
                       entities=['data_contract'])
    target = _workflow(db_session, 'Review copy', active=False,
                       entities=['data_contract'])
    audit = MagicMock()

    result = _toggle(db_session, target, audit, confirm=True)

    assert result.is_active is True
    details = audit.log_action.call_args.kwargs['details']
    assert details['overlap_confirmed'] is True
    assert details['conflicting_workflow_ids'] == [active.id]


def _create_model(name='Review copy'):
    return ProcessWorkflowCreate(
        name=name,
        trigger=WorkflowTrigger(type='on_request_review', entity_types=['data_contract']),
        scope=WorkflowScope(type='all'),
        is_active=True,
        steps=[WorkflowStepCreate(step_id='done', name='Done', step_type='pass')],
    )


def test_create_active_workflow_requires_overlap_confirmation(db_session):
    _workflow(db_session, 'Active review', active=True, entities=['data_contract'])

    with pytest.raises(HTTPException) as raised:
        asyncio.run(create_workflow(
            request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')),
            workflow=_create_model(),
            db=db_session,
            audit_manager=MagicMock(),
            current_user=SimpleNamespace(email='admin@example.com', username='admin'),
            confirm_overlap=False,
            manager=WorkflowsManager(db_session),
            _=True,
        ))

    assert raised.value.status_code == 409
    assert raised.value.detail['params']['conflicts'][0]['name'] == 'Active review'
    assert db_session.query(ProcessWorkflowDb).filter_by(name='Review copy').count() == 0


def test_update_active_workflow_requires_overlap_confirmation(db_session):
    _workflow(db_session, 'Active review', active=True, entities=['data_contract'])
    target = _workflow(db_session, 'Product review', active=True, entities=['data_product'])

    with pytest.raises(HTTPException) as raised:
        asyncio.run(update_workflow(
            request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')),
            workflow_id=target.id,
            workflow=ProcessWorkflowUpdate(
                trigger=WorkflowTrigger(type='on_request_review', entity_types=['data_contract']),
            ),
            db=db_session,
            audit_manager=MagicMock(),
            current_user=SimpleNamespace(email='admin@example.com', username='admin'),
            confirm_overlap=False,
            manager=WorkflowsManager(db_session),
            _=True,
        ))

    assert raised.value.status_code == 409
    unchanged = WorkflowsManager(db_session).get_workflow(target.id)
    assert unchanged.trigger.entity_types == ['data_product']
