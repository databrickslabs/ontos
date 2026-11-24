"""Stored triggers that match no event, in the overlap check and the startup scan (#1151).

A trigger that lists entity types none of which fires (only unknown types such as
``dataset``, or pairs no code fires) consumes no event: it neither overlaps a workflow
for any entity nor is reported as overlapping. The startup scan reads every stored
value, hashable or not, and one unreadable row doesn't stop it. The "warned once"
memory of unknown types is bounded.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import logging
import uuid
from datetime import datetime

import pytest

from src.controller import workflows_manager as wm
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb
from src.models.process_workflows import WorkflowScope, WorkflowTrigger
from src.routes.workflows_routes import _TRIGGER_ENTITY_TYPES


def _stored(db_session, entity_types, *, trigger_type='before_update', active=True):
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=f'gate-{wf_id[:8]}', description='gate',
        trigger_config=json.dumps({'type': trigger_type, 'entity_types': entity_types}),
        scope_config=json.dumps({'type': 'all'}), is_active=active, is_default=False,
        version=1, created_at=now, updated_at=now,
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='ok', name='OK', step_type='pass',
        config='{}', order=0, created_at=now, updated_at=now,
    ))
    db_session.commit()
    return wf_id


def _manager(db_session):
    return WorkflowsManager(db_session, trigger_entity_types=_TRIGGER_ENTITY_TYPES)


def _conflict_ids(manager, trigger):
    return {c['id'] for c in manager.activation_conflicts_for(
        WorkflowTrigger(**trigger), WorkflowScope(type='all'),
    )}


@pytest.mark.parametrize('stored', [['dataset'], ['data_product'], ['dataset', 'data_product']],
                         ids=['unknown', 'unfired-pair', 'both'])
def test_a_stored_trigger_matching_no_event_overlaps_nothing(db_session, stored):
    wf_id = _stored(db_session, stored)

    assert wf_id not in _conflict_ids(_manager(db_session), {'type': 'before_update'})


def test_a_trigger_matching_no_event_has_no_overlaps(db_session):
    _stored(db_session, [])  # any entity

    assert _conflict_ids(_manager(db_session), {
        'type': 'before_update', 'entity_types': ['data_product'],
    }) == set()
    assert _conflict_ids(_manager(db_session), {
        'type': 'before_update', 'unknown_entity_types': ['dataset'],
    }) == set()


def test_only_the_types_that_fire_are_compared(db_session):
    # Both list table, which on_publish never fires for: they share no event
    wf_id = _stored(db_session, ['table', 'data_contract'], trigger_type='on_publish')

    manager = _manager(db_session)
    assert wf_id not in _conflict_ids(manager, {
        'type': 'on_publish', 'entity_types': ['table', 'data_product'],
    })
    conflicts = manager.activation_conflicts_for(
        WorkflowTrigger(type='on_publish', entity_types=['data_contract']),
        WorkflowScope(type='all'),
    )
    assert [c['entity_types'] for c in conflicts if c['id'] == wf_id] == [['data_contract']]


def test_triggers_that_fire_still_overlap(db_session):
    any_id = _stored(db_session, [])
    contract_id = _stored(db_session, ['data_contract'])

    assert {any_id, contract_id} <= _conflict_ids(_manager(db_session), {
        'type': 'before_update', 'entity_types': ['data_contract'],
    })


def test_the_startup_scan_survives_an_unhashable_stored_value(db_session, caplog):
    odd_id = _stored(db_session, [['nested'], {'a': 1}, 'data_contract'])
    later_id = _stored(db_session, ['dataset'])

    with caplog.at_level(logging.WARNING):
        warned = _manager(db_session).log_unmatched_trigger_entity_types()

    assert warned >= 2
    messages = [r.getMessage() for r in caplog.records]
    assert any(odd_id in m and "unknown [\"['nested']\", \"{'a': 1}\"]" in m for m in messages)
    assert any(later_id in m and "['dataset']" in m for m in messages)


def test_one_unreadable_row_does_not_stop_the_scan(db_session, caplog, monkeypatch):
    broken_id = _stored(db_session, ['dataset'])
    later_id = _stored(db_session, ['data_product'])
    manager = _manager(db_session)
    to_model = manager._db_to_model

    def failing(db_workflow):
        if db_workflow.id == broken_id:
            raise RuntimeError('bad row')
        return to_model(db_workflow)

    monkeypatch.setattr(manager, '_db_to_model', failing)
    with caplog.at_level(logging.WARNING):
        manager.log_unmatched_trigger_entity_types()

    messages = [r.getMessage() for r in caplog.records]
    assert f'Could not check the trigger of workflow {broken_id}' in messages
    assert any(later_id in m and 'match no event' in m for m in messages)


def test_the_warned_once_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(wm, '_WARNED_UNKNOWN_ENTITY_TYPES', type(wm._WARNED_UNKNOWN_ENTITY_TYPES)())
    monkeypatch.setattr(wm, '_WARNED_UNKNOWN_ENTITY_TYPES_MAX', 3)

    assert [wm._first_unknown_entity_type_warning((i, ('dataset',))) for i in range(5)] \
        == [True] * 5
    assert len(wm._WARNED_UNKNOWN_ENTITY_TYPES) == 3
    assert wm._first_unknown_entity_type_warning((4, ('dataset',))) is False
    # The oldest keys were forgotten, so they are warned about again
    assert wm._first_unknown_entity_type_warning((0, ('dataset',))) is True
