"""Trigger entity types over the workflow API (#1151 items 6 and 7a).

A workflow stored with an entity type the app no longer knows (``dataset``)
came back as ``entity_types: []``, and saving that body stored ``[]``: the
workflow then fired for every entity.
"""
import json
import uuid
from datetime import datetime

import pytest

from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb


def _stored(db_session, entity_types, trigger_type='before_update', active=False):
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


def test_get_shows_the_unknown_type_and_a_trigger_put_keeps_it(client, db_session):
    wf_id = _stored(db_session, ['dataset'])

    fetched = client.get(f'/api/workflows/{wf_id}')
    assert fetched.status_code == 200, fetched.text
    trigger = fetched.json()['trigger']
    assert trigger['entity_types'] == []
    assert trigger['unknown_entity_types'] == ['dataset']

    # The trigger sent back unchanged is not checked, and keeps the stored value
    saved = client.put(f'/api/workflows/{wf_id}', json={'trigger': trigger})

    assert saved.status_code == 200, saved.text
    assert _stored_types(db_session, wf_id) == ['dataset']


def _issue_codes(detail):
    return [(issue['code'], issue['params']) for issue in detail['params']['issues']]


def _designer_body(client, wf_id):
    """What the designer PUTs for a loaded workflow: the trigger with its unknown types."""
    body = client.get(f'/api/workflows/{wf_id}').json()
    return {key: body[key] for key in ('name', 'description', 'trigger', 'workflow_type',
                                       'is_active', 'steps')}


def test_a_designer_save_that_keeps_the_trigger_succeeds(client, db_session):
    wf_id = _stored(db_session, ['dataset'])
    body = _designer_body(client, wf_id)
    assert body['trigger']['unknown_entity_types'] == ['dataset']
    body['description'] = 'edited'

    saved = client.put(f'/api/workflows/{wf_id}', json=body)

    assert saved.status_code == 200, saved.text
    assert saved.json()['description'] == 'edited'
    assert _stored_types(db_session, wf_id) == ['dataset']


def test_a_step_only_edit_of_an_unknown_type_workflow_succeeds(client, db_session):
    wf_id = _stored(db_session, ['dataset'])
    steps = [{'step_id': 'done', 'name': 'Done', 'step_type': 'pass', 'order': 0}]

    saved = client.put(f'/api/workflows/{wf_id}', json={'steps': steps})

    assert saved.status_code == 200, saved.text
    assert [step['step_id'] for step in saved.json()['steps']] == ['done']
    assert _stored_types(db_session, wf_id) == ['dataset']


def test_a_designer_save_adding_an_unsupported_pair_is_refused(client, db_session):
    wf_id = _stored(db_session, ['dataset'])
    body = _designer_body(client, wf_id)
    body['trigger']['entity_types'] = ['data_product']

    saved = client.put(f'/api/workflows/{wf_id}', json=body)

    assert saved.status_code == 400, saved.text
    detail = saved.json()['detail']
    assert detail['code'] == 'workflow_invalid'
    assert _issue_codes(detail) == [
        ('trigger_entity_type_unsupported',
         {'triggerType': 'before_update', 'entityType': 'data_product'}),
    ]
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


_CONTRACT_TRIGGER = {'type': 'before_update', 'entity_types': ['data_contract']}


def test_emptying_a_trigger_of_only_unknown_types_is_refused(client, db_session):
    wf_id = _stored(db_session, ['dataset'])

    saved = client.put(f'/api/workflows/{wf_id}',
                       json={'trigger': {'type': 'before_update', 'entity_types': []}})

    assert saved.status_code == 400, saved.text
    assert _issue_codes(saved.json()['detail']) == [
        ('trigger_entity_type_required', {'triggerType': 'before_update'}),
    ]
    assert _stored_types(db_session, wf_id) == ['dataset']

    picked = client.put(f'/api/workflows/{wf_id}', json={'trigger': _CONTRACT_TRIGGER})
    assert picked.status_code == 200, picked.text
    assert _stored_types(db_session, wf_id) == ['data_contract']


def test_an_active_unknown_type_gate_taking_a_known_type_gets_the_overlap_check(
    client, db_session,
):
    wf_id = _stored(db_session, ['dataset'], active=True)
    _stored(db_session, ['data_contract'], active=True)

    saved = client.put(f'/api/workflows/{wf_id}', json={'trigger': _CONTRACT_TRIGGER})

    assert saved.status_code == 409, saved.text
    assert saved.json()['detail']['code'] == 'workflow_activation_overlap'
    assert _stored_types(db_session, wf_id) == ['dataset']


def test_a_trigger_only_put_of_a_pair_no_code_fires_is_refused(client, db_session):
    wf_id = _stored(db_session, ['data_contract'])

    saved = client.put(f'/api/workflows/{wf_id}', json={'trigger': _UNSUPPORTED['trigger']})

    assert saved.status_code == 400, saved.text
    assert _issue_codes(saved.json()['detail']) == [
        ('trigger_entity_type_unsupported',
         {'triggerType': 'before_update', 'entityType': 'data_product'}),
    ]
    assert _stored_types(db_session, wf_id) == ['data_contract']


_KNOWN_AS_UNKNOWN = {
    'type': 'before_update', 'entity_types': [], 'unknown_entity_types': ['data_product'],
}


@pytest.mark.parametrize('with_steps', [False, True])
def test_a_known_type_sent_as_unknown_is_refused_on_update(client, db_session, with_steps):
    wf_id = _stored(db_session, ['data_contract'])
    body = {'trigger': _KNOWN_AS_UNKNOWN}
    if with_steps:
        body['steps'] = _UNSUPPORTED['steps']

    saved = client.put(f'/api/workflows/{wf_id}', json=body)

    assert saved.status_code == 400, saved.text
    assert _issue_codes(saved.json()['detail']) == [
        ('trigger_entity_type_unknown',
         {'triggerType': 'before_update', 'entityType': 'data_product'}),
    ]
    assert _stored_types(db_session, wf_id) == ['data_contract']


def test_a_known_type_sent_as_unknown_is_refused_on_create(client, db_session):
    created = client.post('/api/workflows', json={**_UNSUPPORTED, 'name': 'Smuggled type',
                                                  'trigger': _KNOWN_AS_UNKNOWN})

    assert created.status_code == 400, created.text
    assert [code for code, _ in _issue_codes(created.json()['detail'])] == [
        'trigger_entity_type_unknown',
    ]
    assert db_session.query(ProcessWorkflowDb).filter_by(name='Smuggled type').count() == 0
