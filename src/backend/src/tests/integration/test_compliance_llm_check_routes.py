"""LLM_CHECK through the compliance API: a run, its results, and the rule test (#1479)."""
import json
from unittest.mock import patch

import pytest

from src.db_models.data_domains import DataDomain
from src.tests.helpers import FakeLlm, llm_reply

GRAIN = 'states the grain of the table'
RULE = f"MATCH (d:domain)\nASSERT LLM_CHECK(d.description, '{GRAIN}')"


def _answer(kwargs):
    if ' per ' in kwargs['messages'][1]['content']:
        return llm_reply('PASS: one row per order and day')
    return llm_reply('FAIL: does not say what one row is')


@pytest.fixture
def domains(db_session):
    rows = [
        DataDomain(name='orders', description='One row per order and day.', created_by='t'),
        DataDomain(name='misc', description='table with data', created_by='t'),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


@pytest.fixture
def llm(test_settings):
    """LLM features on, with a fake serving endpoint."""
    settings = test_settings.model_copy(update={'LLM_ENABLED': True, 'LLM_ENDPOINT': 'fake-ep'})
    fake = FakeLlm(answer=_answer)
    with patch('src.common.config.get_settings', return_value=settings), \
            patch('src.common.llm_client.create_openai_client', return_value=fake):
        yield fake


def _create_policy(client, rule=RULE):
    response = client.post('/api/compliance/policies', json={
        'name': 'Grain documented', 'description': 'Domains state their grain',
        'rule': rule, 'category': 'Governance', 'severity': 'medium',
    })
    assert response.status_code == 200, response.text
    assert response.json()['warnings'] == []
    return response.json()['id']


def _run(client, policy_id):
    response = client.post(f'/api/compliance/policies/{policy_id}/runs', json={'mode': 'inline'})
    assert response.status_code == 200, response.text
    return response.json()


def test_run_fails_the_entity_with_the_reason_and_reruns_from_the_cache(client, domains, llm):
    policy_id = _create_policy(client)

    run = _run(client, policy_id)

    assert (run['status'], run['success_count'], run['failure_count']) == ('succeeded', 1, 1)
    results = client.get(f"/api/compliance/runs/{run['id']}/results?only_failed=true").json()
    [failed] = results['results']
    assert failed['object_name'] == 'misc'
    [check] = json.loads(failed['details_json'])['llm_checks']
    assert check == {
        'criterion': GRAIN, 'passed': False, 'reason': 'does not say what one row is',
        'code': None, 'cached': False,
    }
    assert len(llm.calls) == 2

    rerun = _run(client, policy_id)

    assert (rerun['success_count'], rerun['failure_count']) == (1, 1)
    assert len(llm.calls) == 2  # unchanged descriptions: no model call


def test_run_without_endpoint_fails_closed(client, domains, test_settings):
    policy_id = _create_policy(client)
    fake = FakeLlm(answer=_answer)
    settings = test_settings.model_copy(update={'LLM_ENABLED': True, 'LLM_ENDPOINT': None})

    with patch('src.common.config.get_settings', return_value=settings), \
            patch('src.common.llm_client.create_openai_client', return_value=fake):
        run = _run(client, policy_id)

    assert (run['success_count'], run['failure_count']) == (0, 2)
    assert fake.calls == []
    results = client.get(f"/api/compliance/runs/{run['id']}/results").json()['results']
    codes = {json.loads(r['details_json'])['llm_checks'][0]['code'] for r in results}
    assert codes == {'llm_check_no_endpoint'}


def test_rule_test_on_a_named_sample_entity(client, domains, llm):
    response = client.post('/api/compliance/llm-check/test', json={'rule': RULE, 'entity': 'misc'})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body['entity_type'], body['entity_name'], body['passed']) == ('domain', 'misc', False)
    assert body['error_code'] is None
    assert body['llm_checks'] == [{
        'criterion': GRAIN, 'passed': False, 'reason': 'does not say what one row is',
        'code': None, 'cached': False,
    }]


def test_rule_test_reports_a_coded_failure(client, domains, test_settings):
    settings = test_settings.model_copy(update={'LLM_ENABLED': False})

    with patch('src.common.config.get_settings', return_value=settings):
        response = client.post('/api/compliance/llm-check/test', json={'rule': RULE})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body['passed'], body['error_code']) == (False, 'llm_check_disabled')
    assert body['llm_checks'][0]['code'] == 'llm_check_disabled'


def test_rule_test_without_a_matching_entity(client, domains, llm):
    response = client.post('/api/compliance/llm-check/test', json={'rule': RULE, 'entity': 'nope'})

    assert response.status_code == 404
    assert response.json()['detail']['code'] == 'sample_entity_not_found'
    assert llm.calls == []


def test_rule_test_rejects_a_rule_that_does_not_parse(client, llm):
    response = client.post('/api/compliance/llm-check/test', json={'rule': 'ASSERT LLM_CHECK('})

    assert response.status_code == 422


@pytest.fixture(autouse=True)
def _no_rule_test_history():
    from src.routes import compliance_routes

    compliance_routes._rule_tests.clear()
    yield
    compliance_routes._rule_tests.clear()


def test_rule_tests_are_throttled_per_user(client, domains, llm, monkeypatch):
    from src.routes import compliance_routes

    monkeypatch.setattr(compliance_routes, 'RULE_TEST_MAX_CALLS', 2)
    for _ in range(2):
        ok = client.post('/api/compliance/llm-check/test', json={'rule': RULE})
        assert ok.status_code == 200, ok.text

    limited = client.post('/api/compliance/llm-check/test', json={'rule': RULE})

    assert limited.status_code == 429
    assert limited.json()['detail']['code'] == 'llm_check_test_rate_limited'
    assert int(limited.headers['Retry-After']) >= 1


def test_saving_a_rule_with_entity_data_as_criterion_is_rejected(client):
    response = client.post('/api/compliance/policies', json={
        'name': 'Injected', 'description': 'd', 'category': 'Governance', 'severity': 'low',
        'rule': 'MATCH (d:domain)\nASSERT LLM_CHECK(d.description, d.name)',
    })

    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'llm_check_criterion_not_literal'


def test_the_settings_save_returns_the_job_warnings(client, monkeypatch):
    from src.controller.settings_manager import SettingsManager

    warning = {'code': 'compliance_job_not_updated', 'params': {}, 'message': 'm'}
    monkeypatch.setattr(SettingsManager, '_refresh_llm_job_parameters', lambda self: warning)
    calls = []
    real = SettingsManager.update_settings_with_warnings
    monkeypatch.setattr(
        SettingsManager, 'update_settings_with_warnings',
        lambda self, payload: calls.append(payload) or real(self, payload),
    )

    response = client.put('/api/settings', json={'llm_endpoint': 'new-endpoint'})

    assert response.status_code == 200, response.text
    assert response.json()['warnings'] == [warning]
    assert len(calls) == 1


def test_expired_rule_test_entries_are_dropped(monkeypatch):
    from src.routes import compliance_routes

    clock = [1000.0]
    monkeypatch.setattr(compliance_routes.time, 'monotonic', lambda: clock[0])
    for user in ('a@x', 'b@x', 'c@x'):
        compliance_routes._throttle_rule_test(user)

    clock[0] += compliance_routes.RULE_TEST_WINDOW_SECONDS
    compliance_routes._throttle_rule_test('d@x')

    assert set(compliance_routes._rule_tests) == {'d@x'}
