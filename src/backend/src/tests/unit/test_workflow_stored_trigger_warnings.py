"""Stored workflows whose trigger entity types match no event are flagged and logged (#1151).

A workflow stored before the save checks can list an entity type the app no longer
knows (``dataset``) or a pair no code fires (``before_update`` on ``data_product``).
It is kept as stored, and its read model lists the entity types in
``trigger_warnings`` (coded, with ``triggerType`` / ``entityType``). At startup one
warning per such workflow is logged, with its id, name, trigger type and entity types.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import contextlib
import json
import logging
import uuid
from datetime import datetime
from unittest.mock import patch

from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb
from src.routes.workflows_routes import _TRIGGER_ENTITY_TYPES

UNKNOWN = 'stored_entity_type_unknown'
UNSUPPORTED = 'stored_entity_type_unsupported'


def _stored(db_session, entity_types, *, trigger_type='before_update', active=True, name=None):
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=name or f'gate-{wf_id[:8]}', description='gate',
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


def _warnings(workflow):
    return [(w.code, w.params) for w in workflow.trigger_warnings]


def _row(db_session, wf_id):
    db_session.expire_all()
    row = db_session.get(ProcessWorkflowDb, wf_id)
    return row.trigger_config, row.is_active


def test_an_unknown_type_is_flagged_next_to_a_known_one(db_session):
    wf_id = _stored(db_session, ['dataset', 'data_contract'])

    assert _warnings(_manager(db_session).get_workflow(wf_id)) == [
        (UNKNOWN, {'triggerType': 'before_update', 'entityType': 'dataset'}),
    ]


def test_a_stored_pair_no_code_fires_is_flagged(db_session):
    wf_id = _stored(db_session, ['data_product', 'data_contract'])

    assert _warnings(_manager(db_session).get_workflow(wf_id)) == [
        (UNSUPPORTED, {'triggerType': 'before_update', 'entityType': 'data_product'}),
    ]


def test_matching_triggers_have_no_warnings(db_session):
    manager = _manager(db_session)
    ids = [
        _stored(db_session, ['data_contract']),
        _stored(db_session, []),  # any entity
        _stored(db_session, ['data_product', 'table'], trigger_type='manual'),  # any entity
    ]

    assert [_warnings(manager.get_workflow(wf_id)) for wf_id in ids] == [[], [], []]


def test_without_the_map_only_unknown_types_are_flagged(db_session):
    wf_id = _stored(db_session, ['dataset', 'data_product'])

    assert [w.code for w in WorkflowsManager(db_session).get_workflow(wf_id).trigger_warnings] \
        == [UNKNOWN]


def test_the_list_carries_the_warnings(db_session):
    wf_id = _stored(db_session, ['dataset'])

    listed = {wf.id: wf for wf in _manager(db_session).list_workflows()}

    assert [w.code for w in listed[wf_id].trigger_warnings] == [UNKNOWN]


def test_the_startup_check_logs_each_workflow_once_and_changes_nothing(db_session, caplog):
    manager = _manager(db_session)
    unknown_id = _stored(db_session, ['dataset'], name='Old Gate')
    unsupported_id = _stored(db_session, ['data_product'], active=False, name='Product Gate')
    fine_id = _stored(db_session, ['data_contract'])
    rows_before = {wf_id: _row(db_session, wf_id)
                   for wf_id in (unknown_id, unsupported_id, fine_id)}

    with caplog.at_level(logging.WARNING):
        warned = manager.log_unmatched_trigger_entity_types()
        # A later read doesn't log the unknown type again
        manager.get_workflow(unknown_id)

    messages = [r.getMessage() for r in caplog.records]
    assert warned == 2
    assert [m for m in messages if unknown_id in m] == [
        f"Workflow {unknown_id} ('Old Gate', active, trigger before_update) lists entity "
        "types that match no event: unknown ['dataset'], not fired for this trigger []. "
        "It is kept as stored.",
    ]
    assert [m for m in messages if unsupported_id in m] == [
        f"Workflow {unsupported_id} ('Product Gate', inactive, trigger before_update) lists "
        "entity types that match no event: unknown [], not fired for this trigger "
        "['data_product']. It is kept as stored.",
    ]
    assert not [m for m in messages if fine_id in m]
    assert {wf_id: _row(db_session, wf_id) for wf_id in rows_before} == rows_before


def test_startup_seeding_runs_the_check_with_the_route_map(db_session, caplog):
    from src import app as app_module

    wf_id = _stored(db_session, ['data_product'])

    def factory():
        return contextlib.nullcontext(db_session)

    with patch('src.common.database.get_session_factory', return_value=factory), \
            caplog.at_level(logging.WARNING):
        app_module._warn_unmatched_trigger_entity_types()

    # The pair is found only with the trigger/entity map of the workflow routes
    assert any(wf_id in r.getMessage() and "['data_product']" in r.getMessage()
               for r in caplog.records)
    assert any('1 workflow(s) list trigger entity types' in r.getMessage()
               for r in caplog.records)


def test_startup_seeding_calls_the_check():
    from src import app as app_module

    with patch('src.common.database.get_session_factory', side_effect=RuntimeError('no db')), \
            patch.object(app_module, '_warn_unmatched_trigger_entity_types') as check:
        app_module._seed_default_workflows()

    # It runs even when seeding failed
    check.assert_called_once_with()
