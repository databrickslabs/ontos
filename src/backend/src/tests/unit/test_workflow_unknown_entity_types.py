"""Unknown stored trigger entity types never widen a workflow to "any entity" (#1151 item 6).

A stored value that is no ``EntityType`` (the removed ``dataset``) was dropped
when the workflow was read, so the API returned ``entity_types: []`` ("any
entity"), and saving that body back stored ``[]``: the workflow then fired for
every entity of its trigger type. Unknown values are now returned in
``unknown_entity_types`` and written back as stored, so they keep matching
nothing.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import logging
import uuid
from datetime import datetime

from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowUpdate,
    TriggerType,
    WorkflowTrigger,
)


def _stored(db_session, entity_types, *, trigger_type='before_update', active=True):
    """A workflow row as an older version stored it, with one Pass step."""
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


def _stored_types(db_session, wf_id):
    db_session.expire_all()
    return json.loads(db_session.get(ProcessWorkflowDb, wf_id).trigger_config)['entity_types']


def _matching_ids(manager, entity_type):
    return {
        wf.id for wf in
        manager.get_workflows_for_trigger(TriggerType.BEFORE_UPDATE, entity_type)
    }


def test_unknown_types_are_returned_next_to_the_known_ones(db_session):
    wf_id = _stored(db_session, ['data_contract', 'dataset'])

    trigger = WorkflowsManager(db_session).get_workflow(wf_id).trigger

    assert trigger.entity_types == [EntityType.DATA_CONTRACT]
    assert trigger.unknown_entity_types == ['dataset']


def test_saving_the_returned_trigger_keeps_an_only_unknown_type(db_session):
    manager = WorkflowsManager(db_session)
    wf_id = _stored(db_session, ['dataset'])

    fetched = manager.get_workflow(wf_id)
    assert fetched.trigger.entity_types == []
    manager.update_workflow(wf_id, ProcessWorkflowUpdate(trigger=fetched.trigger))

    assert _stored_types(db_session, wf_id) == ['dataset']
    # Still matches no event, rather than every entity
    assert wf_id not in _matching_ids(manager, EntityType.DATA_CONTRACT)
    assert wf_id not in _matching_ids(manager, EntityType.DATA_PRODUCT)


def test_mixed_types_match_the_known_one_only_after_a_save(db_session):
    manager = WorkflowsManager(db_session)
    wf_id = _stored(db_session, ['data_contract', 'dataset'])

    trigger = manager.get_workflow(wf_id).trigger
    manager.update_workflow(wf_id, ProcessWorkflowUpdate(trigger=trigger))

    assert _stored_types(db_session, wf_id) == ['data_contract', 'dataset']
    assert wf_id in _matching_ids(manager, EntityType.DATA_CONTRACT)
    assert wf_id not in _matching_ids(manager, EntityType.DATA_PRODUCT)


def test_a_duplicate_keeps_the_unknown_types(db_session):
    manager = WorkflowsManager(db_session)
    wf_id = _stored(db_session, ['dataset'])

    copy = manager.duplicate_workflow(wf_id, f'copy-{wf_id[:8]}')
    manager.toggle_active(copy.id, True)

    assert copy.trigger.unknown_entity_types == ['dataset']
    assert _stored_types(db_session, copy.id) == ['dataset']
    assert copy.id not in _matching_ids(manager, EntityType.DATA_CONTRACT)


def test_unknown_types_are_logged_once_not_on_every_read(db_session, caplog):
    manager = WorkflowsManager(db_session)
    wf_id = _stored(db_session, ['dataset', 'legacy_thing'])

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            manager.get_workflow(wf_id)
        manager.list_workflows()

    warnings = [r for r in caplog.records if 'unknown entity types' in r.getMessage()
                and wf_id in r.getMessage()]
    assert len(warnings) == 1


def test_an_only_unknown_trigger_overlaps_no_active_workflow(db_session):
    manager = WorkflowsManager(db_session)
    _stored(db_session, ['data_contract'])

    conflicts = manager.activation_conflicts_for(
        WorkflowTrigger(type=TriggerType.BEFORE_UPDATE, unknown_entity_types=['dataset']),
        None,
    )

    assert conflicts == []
