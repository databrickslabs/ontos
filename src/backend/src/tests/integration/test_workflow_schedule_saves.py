"""Saving a scheduled workflow over the API keeps its schedule valid (#941).

The designer doesn't edit schedules: it PUTs the trigger without ``schedule`` and
``timezone``, and the stored ones are kept. A PUT that sends only the trigger checks the
schedule as well.
"""
import json
import uuid
from datetime import datetime

import pytest

from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb


def _stored_scheduled(db_session, schedule='0 0 6 * * ?', timezone='Europe/Berlin'):
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=f'scheduled-{wf_id[:8]}', description='scheduled',
        trigger_config=json.dumps({
            'type': 'scheduled', 'entity_types': [], 'schedule': schedule, 'timezone': timezone,
        }),
        scope_config=json.dumps({'type': 'all'}), is_active=False, is_default=False,
        version=1, created_at=now, updated_at=now,
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='ok', name='OK', step_type='pass',
        config='{}', order=0, created_at=now, updated_at=now,
    ))
    db_session.commit()
    return wf_id


def _stored_trigger(db_session, wf_id):
    db_session.expire_all()
    return json.loads(db_session.get(ProcessWorkflowDb, wf_id).trigger_config)


def _designer_body(client, wf_id):
    """What workflow-designer.tsx PUTs: the trigger without schedule and timezone."""
    body = client.get(f'/api/workflows/{wf_id}').json()
    trigger = {'type': body['trigger']['type'], 'entity_types': body['trigger']['entity_types']}
    return {
        'name': body['name'], 'description': body['description'], 'trigger': trigger,
        'workflow_type': body['workflow_type'], 'is_active': body['is_active'],
        'steps': body['steps'],
    }


def _issue_codes(response):
    return [issue['code'] for issue in response.json()['detail']['params']['issues']]


def test_a_designer_save_keeps_the_stored_schedule_and_timezone(client, db_session):
    wf_id = _stored_scheduled(db_session)
    body = _designer_body(client, wf_id)
    body['description'] = 'edited'

    saved = client.put(f'/api/workflows/{wf_id}', json=body)

    assert saved.status_code == 200, saved.text
    stored = _stored_trigger(db_session, wf_id)
    assert stored['schedule'] == '0 0 6 * * ?'
    assert stored['timezone'] == 'Europe/Berlin'


def test_a_schedule_sent_empty_is_still_refused(client, db_session):
    wf_id = _stored_scheduled(db_session)
    body = _designer_body(client, wf_id)
    body['trigger']['schedule'] = ''

    saved = client.put(f'/api/workflows/{wf_id}', json=body)

    assert saved.status_code == 400, saved.text
    assert 'schedule_required' in _issue_codes(saved)


def test_validate_with_the_workflow_id_keeps_the_stored_schedule(client, db_session):
    wf_id = _stored_scheduled(db_session)
    body = _designer_body(client, wf_id)

    checked = client.post('/api/workflows/validate', params={'workflow_id': wf_id}, json=body)

    assert checked.status_code == 200, checked.text
    assert checked.json()['valid'] is True, checked.text


@pytest.mark.parametrize('schedule, timezone, code', [
    ('0 6 * * *', 'UTC', 'cron_field_count'),
    ('0 * * * * ?', 'UTC', 'cron_interval_too_short'),
    ('0 0 6 * * ?', 'Mars/Olympus', 'timezone_invalid'),
])
def test_a_trigger_only_put_checks_the_schedule(client, db_session, schedule, timezone, code):
    wf_id = _stored_scheduled(db_session)
    trigger = {'type': 'scheduled', 'schedule': schedule, 'timezone': timezone}

    saved = client.put(f'/api/workflows/{wf_id}', json={'trigger': trigger})

    assert saved.status_code == 400, saved.text
    assert code in _issue_codes(saved)
    assert _stored_trigger(db_session, wf_id)['schedule'] == '0 0 6 * * ?'


def test_a_trigger_only_put_with_a_valid_schedule_is_saved(client, db_session):
    wf_id = _stored_scheduled(db_session)
    trigger = {'type': 'scheduled', 'schedule': '0 30 7 ? * MON-FRI', 'timezone': 'UTC'}

    saved = client.put(f'/api/workflows/{wf_id}', json={'trigger': trigger})

    assert saved.status_code == 200, saved.text
    assert _stored_trigger(db_session, wf_id)['schedule'] == '0 30 7 ? * MON-FRI'
