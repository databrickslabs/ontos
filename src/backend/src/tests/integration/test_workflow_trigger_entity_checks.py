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


def _issue_codes(detail):
    return [(issue['code'], issue['params']) for issue in detail['params']['issues']]


def test_saving_the_get_body_of_an_unknown_type_is_refused_and_keeps_it(client, db_session):
    wf_id = _stored(db_session, ['dataset'])
    body = client.get(f'/api/workflows/{wf_id}').json()

    saved = client.put(f'/api/workflows/{wf_id}', json=body)

    assert saved.status_code == 400, saved.text
    detail = saved.json()['detail']
    assert detail['code'] == 'workflow_invalid'
    assert _issue_codes(detail) == [('trigger_entity_type_unknown',
                                     {'triggerType': 'before_update', 'entityType': 'dataset'})]
    assert _stored_types(db_session, wf_id) == ['dataset']


_UNSUPPORTED = {
    'name': 'Product update gate',
    'trigger': {'type': 'before_update', 'entity_types': ['data_product']},
    'is_active': False,
    'steps': [{'step_id': 'ok', 'name': 'OK', 'step_type': 'pass', 'order': 0}],
}


def test_creating_a_pair_no_code_fires_is_refused_with_its_code(client, db_session):
    created = client.post('/api/workflows', json=_UNSUPPORTED)

    assert created.status_code == 400, created.text
    assert _issue_codes(created.json()['detail']) == [
        ('trigger_entity_type_unsupported',
         {'triggerType': 'before_update', 'entityType': 'data_product'}),
    ]
    assert db_session.query(ProcessWorkflowDb).filter_by(name=_UNSUPPORTED['name']).count() == 0


def test_validate_reports_the_pair(client):
    result = client.post('/api/workflows/validate', json=_UNSUPPORTED)

    assert result.status_code == 200, result.text
    assert result.json()['valid'] is False
    assert [issue['code'] for issue in result.json()['issues']] == [
        'trigger_entity_type_unsupported',
    ]
