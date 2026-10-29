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
              scope_type='all', scope_ids=None, from_status=None, to_status=None,
              schedule=None):
    row = ProcessWorkflowDb(
        id=str(uuid4()), name=name, is_active=active, workflow_type='process',
        trigger_config=json.dumps({
            'type': trigger, 'entity_types': entities or [],
            'from_status': from_status, 'to_status': to_status, 'schedule': schedule,
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


def test_distinct_entity_types_do_not_conflict(db_session):
    _workflow(db_session, 'Product review', active=True, entities=['data_product'])
    target = _workflow(db_session, 'Target', active=False, entities=['data_contract'],
                       scope_type='domain', scope_ids=['domain-a'])

    assert WorkflowsManager(db_session).activation_conflicts(target.id) == []


def test_distinct_scopes_still_conflict_until_runtime_events_carry_scope(db_session):
    active = _workflow(db_session, 'Domain B', active=True, entities=['data_contract'],
                       scope_type='domain', scope_ids=['domain-b'])
    target = _workflow(db_session, 'Domain A', active=False, entities=['data_contract'],
                       scope_type='domain', scope_ids=['domain-a'])

    assert [item['id'] for item in WorkflowsManager(db_session).activation_conflicts(target.id)] == [active.id]


def test_global_and_scoped_workflows_conflict(db_session):
    active = _workflow(db_session, 'Global', active=True, entities=['data_contract'])
    target = _workflow(db_session, 'Domain A', active=False, entities=['data_contract'],
                       scope_type='domain', scope_ids=['domain-a'])

    assert [item['id'] for item in WorkflowsManager(db_session).activation_conflicts(target.id)] == [active.id]


def test_status_filters_only_disambiguate_status_change_triggers(db_session):
    request_active = _workflow(
        db_session, 'Request active', active=True, trigger='on_request_status_change',
        entities=['data_product'], to_status='active',
    )
    request_deprecated = _workflow(
        db_session, 'Request deprecated', active=False, trigger='on_request_status_change',
        entities=['data_product'], to_status='deprecated',
    )
    transition_active = _workflow(
        db_session, 'Transition active', active=True, trigger='on_status_change',
        entities=['data_product'], to_status='active',
    )
    transition_deprecated = _workflow(
        db_session, 'Transition deprecated', active=False, trigger='on_status_change',
        entities=['data_product'], to_status='deprecated',
    )

    assert [item['id'] for item in WorkflowsManager(db_session).activation_conflicts(request_deprecated.id)] == [request_active.id]
    assert WorkflowsManager(db_session).activation_conflicts(transition_deprecated.id) == []


def test_status_change_same_and_wildcard_filters_overlap(db_session):
    same = _workflow(
        db_session, 'Same transition', active=True, trigger='on_status_change',
        entities=['data_product'], to_status='active',
    )
    wildcard = _workflow(
        db_session, 'Any transition', active=True, trigger='on_status_change',
        entities=['data_product'],
    )
    target = _workflow(
        db_session, 'Target transition', active=False, trigger='on_status_change',
        entities=['data_product'], to_status='active',
    )

    assert {item['id'] for item in WorkflowsManager(db_session).activation_conflicts(target.id)} == {
        same.id, wildcard.id,
    }


def test_empty_entity_list_is_a_wildcard(db_session):
    active = _workflow(db_session, 'All entities', active=True, entities=[])
    target = _workflow(db_session, 'Contract review', active=False,
                       entities=['data_contract'])

    conflicts = WorkflowsManager(db_session).activation_conflicts(target.id)
    assert [item['id'] for item in conflicts] == [active.id]


def test_manual_workflows_never_conflict(db_session):
    # Manual runs go by workflow id (POST /api/workflows/{id}/execute), not by event.
    _workflow(db_session, 'Manual A', active=True, trigger='manual', entities=['data_product'])
    target = _workflow(db_session, 'Manual B', active=False, trigger='manual',
                       entities=['data_product'])

    assert WorkflowsManager(db_session).activation_conflicts(target.id) == []


def test_scheduled_workflows_never_conflict(db_session):
    # Nothing fires a scheduled trigger event; each schedule belongs to one workflow.
    _workflow(db_session, 'Nightly', active=True, trigger='scheduled', schedule='0 9 * * *')
    target = _workflow(db_session, 'Evening', active=False, trigger='scheduled',
                       schedule='0 18 * * *')

    assert WorkflowsManager(db_session).activation_conflicts(target.id) == []


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


def _create_model(name='Review copy', *, scope=...):
    workflow_scope = WorkflowScope(type='all') if scope is ... else scope
    return ProcessWorkflowCreate(
        name=name,
        trigger=WorkflowTrigger(type='on_request_review', entity_types=['data_contract']),
        scope=workflow_scope,
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


def test_create_with_null_scope_is_treated_as_all(db_session):
    _workflow(db_session, 'Active review', active=True, entities=['data_contract'])

    with pytest.raises(HTTPException) as raised:
        asyncio.run(create_workflow(
            request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')),
            workflow=_create_model(scope=None),
            db=db_session,
            audit_manager=MagicMock(),
            current_user=SimpleNamespace(email='admin@example.com', username='admin'),
            confirm_overlap=False,
            manager=WorkflowsManager(db_session),
            _=True,
        ))

    assert raised.value.status_code == 409
    assert raised.value.detail['code'] == 'workflow_activation_overlap'


def test_confirmed_create_audits_conflicting_workflows(db_session):
    active = _workflow(db_session, 'Active review', active=True, entities=['data_contract'])
    audit = MagicMock()

    result = asyncio.run(create_workflow(
        request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')),
        workflow=_create_model(), db=db_session, audit_manager=audit,
        current_user=SimpleNamespace(email='admin@example.com', username='admin'),
        confirm_overlap=True, manager=WorkflowsManager(db_session), _=True,
    ))

    assert result.is_active is True
    details = audit.log_action.call_args.kwargs['details']
    assert details['overlap_confirmed'] is True
    assert details['conflicting_workflow_ids'] == [active.id]


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


def test_put_activation_requires_confirmation_and_audits_override(db_session):
    active = _workflow(db_session, 'Active review', active=True, entities=['data_contract'])
    target = _workflow(db_session, 'Review copy', active=False, entities=['data_contract'])
    request = SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'))
    user = SimpleNamespace(email='admin@example.com', username='admin')

    with pytest.raises(HTTPException) as raised:
        asyncio.run(update_workflow(
            request=request, workflow_id=target.id,
            workflow=ProcessWorkflowUpdate(is_active=True),
            db=db_session, audit_manager=MagicMock(), current_user=user,
            confirm_overlap=False, manager=WorkflowsManager(db_session), _=True,
        ))
    assert raised.value.status_code == 409
    assert db_session.get(ProcessWorkflowDb, target.id).is_active is False

    audit = MagicMock()
    result = asyncio.run(update_workflow(
        request=request, workflow_id=target.id,
        workflow=ProcessWorkflowUpdate(is_active=True),
        db=db_session, audit_manager=audit, current_user=user,
        confirm_overlap=True, manager=WorkflowsManager(db_session), _=True,
    ))
    assert result.is_active is True
    details = audit.log_action.call_args.kwargs['details']
    assert details['overlap_confirmed'] is True
    assert details['conflicting_workflow_ids'] == [active.id]


def test_renaming_an_already_active_overlap_does_not_require_reconfirmation(db_session):
    _workflow(db_session, 'Active review', active=True, entities=['data_contract'])
    target = _workflow(db_session, 'Review copy', active=True, entities=['data_contract'])

    result = asyncio.run(update_workflow(
        request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')),
        workflow_id=target.id,
        workflow=ProcessWorkflowUpdate(name='Renamed review'),
        db=db_session, audit_manager=MagicMock(),
        current_user=SimpleNamespace(email='admin@example.com', username='admin'),
        confirm_overlap=False, manager=WorkflowsManager(db_session), _=True,
    ))

    assert result.name == 'Renamed review'


def test_deactivation_and_idempotent_activation_skip_overlap_check(db_session):
    _workflow(db_session, 'Active review', active=True, entities=['data_contract'])
    target = _workflow(db_session, 'Review copy', active=True, entities=['data_contract'])

    idempotent = _toggle(db_session, target, MagicMock())
    assert idempotent.is_active is True

    deactivated = asyncio.run(toggle_workflow_active(
        request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')),
        workflow_id=target.id, db=db_session, audit_manager=MagicMock(),
        current_user=SimpleNamespace(email='admin@example.com', username='admin'),
        is_active=False, confirm_overlap=False,
        manager=WorkflowsManager(db_session), _=True,
    ))
    assert deactivated.is_active is False


def _put_trigger(db_session, target, trigger):
    return asyncio.run(update_workflow(
        request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')),
        workflow_id=target.id,
        workflow=ProcessWorkflowUpdate(trigger=trigger),
        db=db_session, audit_manager=MagicMock(),
        current_user=SimpleNamespace(email='admin@example.com', username='admin'),
        confirm_overlap=False, manager=WorkflowsManager(db_session), _=True,
    ))


def _active_gate_pair(db_session):
    _workflow(db_session, 'Gate A', active=True, trigger='before_status_change',
              entities=['data_product'], to_status='active')
    return _workflow(db_session, 'Gate B', active=True, trigger='before_status_change',
                     entities=['data_product'], to_status='active')


def test_gate_settings_edit_on_active_overlap_does_not_reask(db_session):
    target = _active_gate_pair(db_session)

    result = _put_trigger(db_session, target, WorkflowTrigger(
        type='before_status_change', entity_types=['data_product'], to_status='active',
        on_error='fail_closed', disabled_for={'domains': ['domain-a']},
    ))

    assert result.trigger.on_error.value == 'fail_closed'
    assert result.trigger.disabled_for.domains == ['domain-a']


def test_entity_order_change_on_active_overlap_does_not_reask(db_session):
    _workflow(db_session, 'Review A', active=True, entities=['data_contract', 'data_product'])
    target = _workflow(db_session, 'Review B', active=True,
                       entities=['data_contract', 'data_product'])

    result = _put_trigger(db_session, target, WorkflowTrigger(
        type='on_request_review', entity_types=['data_product', 'data_contract'],
    ))

    assert result.trigger.entity_types == ['data_product', 'data_contract']


def test_status_filter_change_on_active_workflow_is_still_checked(db_session):
    _workflow(db_session, 'Gate deprecated', active=True, trigger='before_status_change',
              entities=['data_product'], to_status='deprecated')
    target = _workflow(db_session, 'Gate active', active=True,
                       trigger='before_status_change', entities=['data_product'],
                       to_status='active')

    with pytest.raises(HTTPException) as raised:
        _put_trigger(db_session, target, WorkflowTrigger(
            type='before_status_change', entity_types=['data_product'],
            to_status='deprecated',
        ))

    assert raised.value.status_code == 409
