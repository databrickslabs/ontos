"""Trigger entity types over the workflow API (#1151 items 6 and 7a).

A workflow stored with an entity type the app no longer knows (``dataset``)
came back as ``entity_types: []``, and saving that body stored ``[]``: the
workflow then fired for every entity.
"""
import json
import uuid
from datetime import datetime

from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb


def _stored(db_session, entity_types, trigger_type='before_update'):
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=f'gate-{wf_id[:8]}', description='gate',
        trigger_config=json.dumps({'type': trigger_type, 'entity_types': entity_types}),
        scope_config=json.dumps({'type': 'all'}), is_active=False, is_default=False,
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


def test_get_shows_the_unknown_type_and_a_trigger_put_keeps_it(client, db_session):
    wf_id = _stored(db_session, ['dataset'])

    fetched = client.get(f'/api/workflows/{wf_id}')
    assert fetched.status_code == 200, fetched.text
    trigger = fetched.json()['trigger']
    assert trigger['entity_types'] == []
    assert trigger['unknown_entity_types'] == ['dataset']

    saved = client.put(f'/api/workflows/{wf_id}', json={'trigger': trigger})

    assert saved.status_code == 200, saved.text
    assert _stored_types(db_session, wf_id) == ['dataset']
