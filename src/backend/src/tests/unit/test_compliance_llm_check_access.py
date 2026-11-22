"""Who may run LLM_CHECK rules, and what a user-started run reads (#1479 review)."""
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.features import FeatureAccessLevel
from src.controller.compliance_manager import ComplianceManager, rule_uses_llm_check
from src.db_models.compliance import CompliancePolicyDb

UC_RULE = "MATCH (t:table)\nASSERT LLM_CHECK(t.comment, 'states the grain')"
APP_RULE = "MATCH (p:data_product)\nASSERT LLM_CHECK(p.description, 'says who uses it')"
PLAIN_RULE = "MATCH (t:table)\nASSERT t.comment != ''"


def test_rule_uses_llm_check():
    assert rule_uses_llm_check(UC_RULE)
    assert not rule_uses_llm_check(PLAIN_RULE)
    assert not rule_uses_llm_check(None)
    # A rule that doesn't parse counts when it names LLM_CHECK (the gates err safe)
    assert rule_uses_llm_check("MATCH (t:table ASSERT LLM_CHECK(t.comment, 'x')")


@pytest.fixture
def levels():
    """Feature -> the user's access level; missing features: none."""
    return {'compliance': FeatureAccessLevel.ADMIN, 'data-products': FeatureAccessLevel.READ_ONLY}


@pytest.fixture
def api(levels):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.common.api_errors import coded_http_exception_handler
    from src.common.authorization import get_user_details_from_sdk
    from src.common.dependencies import get_current_user_details_for_audit, get_db
    from src.common.manager_dependencies import get_audit_manager, get_auth_manager
    from src.models.users import UserInfo
    from src.routes import compliance_routes
    from starlette.exceptions import HTTPException as StarletteHTTPException

    app = FastAPI()
    app.include_router(compliance_routes.router)
    app.add_exception_handler(StarletteHTTPException, coded_http_exception_handler)
    app.state.teams_manager = None
    app.state.settings_manager = None
    user = UserInfo(email='w@example.com', username='w', user='W', ip='127.0.0.1', groups=['g'])
    auth = MagicMock()
    auth.has_permission.return_value = True  # route-level READ_WRITE check passes

    async def _user():
        return user

    def _db():
        yield MagicMock()

    app.dependency_overrides[get_user_details_from_sdk] = _user
    app.dependency_overrides[get_current_user_details_for_audit] = _user
    app.dependency_overrides[get_auth_manager] = lambda: auth
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_audit_manager] = lambda: MagicMock()

    def level(auth_manager, u, feature, required, request=None):
        order = [FeatureAccessLevel.READ_ONLY, FeatureAccessLevel.READ_WRITE,
                 FeatureAccessLevel.ADMIN]
        have = levels.get(feature)
        return have is not None and order.index(have) >= order.index(required)

    # The user's identity; its client lists nothing (the run answer's counts)
    user_identity = SimpleNamespace(workspace_client=lambda: None)
    with patch.object(compliance_routes, 'user_has_feature_level', side_effect=level), \
            patch.object(compliance_routes, 'manager') as manager, \
            patch.object(
                compliance_routes.RunIdentity, 'for_request', return_value=user_identity,
            ) as obo:
        manager.run_policy_inline.return_value = SimpleNamespace(
            id='r1', policy_id='p1', status='succeeded', started_at=None, finished_at=None,
            success_count=0, failure_count=0, score=0.0, error_message=None, error_code=None,
            error_params=None, warning_code=None, warning_params=None, llm_calls=2,
            llm_cache_hits=1,
        )
        manager.viewer_run_counts.side_effect = lambda db, runs, checks: {
            r.id: {'success': 0, 'failure': 0, 'not_evaluated': 0, 'hidden': 0} for r in runs
        }
        yield SimpleNamespace(
            http=TestClient(app), manager=manager, obo=obo, user_identity=user_identity,
        )


def _policy(manager, rule):
    manager.get_policy.return_value = SimpleNamespace(id='p1', name='P', rule=rule)


def test_a_user_run_of_an_llm_check_rule_reads_as_the_user(api):
    _policy(api.manager, UC_RULE)

    assert api.http.post('/api/compliance/policies/p1/runs', json={}).status_code == 200

    kwargs = api.manager.run_policy_inline.call_args.kwargs
    assert kwargs['run_identity'] is api.user_identity


def test_the_run_answer_has_the_llm_usage(api):
    _policy(api.manager, PLAIN_RULE)

    body = api.http.post('/api/compliance/policies/p1/runs', json={}).json()

    assert (body['llm_calls'], body['llm_cache_hits']) == (2, 1)


def test_a_user_run_of_a_rule_without_llm_check_reads_as_the_user_too(api):
    # Before, a plain DSL rule started by a user read Unity Catalog as the app
    # (#1486 review); every user-started run now reads as its user (#1387)
    _policy(api.manager, PLAIN_RULE)

    assert api.http.post('/api/compliance/policies/p1/runs', json={}).status_code == 200

    assert api.manager.run_policy_inline.call_args.kwargs['run_identity'] is api.user_identity


def test_without_the_users_token_the_rule_test_is_refused(api):
    from src.common.api_errors import UserTokenRequiredError

    api.manager.test_rule_on_sample.side_effect = UserTokenRequiredError('sign in')

    response = api.http.post('/api/compliance/llm-check/test', json={'rule': UC_RULE})

    assert response.status_code == 403
    assert response.json()['detail']['code'] == 'user_token_required'


def test_an_llm_check_rule_on_app_entities_needs_read_access_to_them(api, levels):
    del levels['data-products']
    _policy(api.manager, APP_RULE)

    response = api.http.post('/api/compliance/policies/p1/runs', json={})

    assert response.status_code == 403
    detail = response.json()['detail']
    assert (detail['code'], detail['params']) == (
        'llm_check_entity_read_required', {'entityType': 'data_product'},
    )
    api.manager.run_policy_inline.assert_not_called()


def test_an_llm_check_rule_on_readable_app_entities_runs(api):
    _policy(api.manager, APP_RULE)

    assert api.http.post('/api/compliance/policies/p1/runs', json={}).status_code == 200


def test_the_rule_test_reads_as_the_user(api):
    from src.models.compliance import LlmCheckTestResponse

    api.manager.test_rule_on_sample.return_value = LlmCheckTestResponse(
        entity_type='table', passed=True,
    )

    response = api.http.post('/api/compliance/llm-check/test', json={'rule': UC_RULE})

    assert response.status_code == 200, response.text
    kwargs = api.manager.test_rule_on_sample.call_args.kwargs
    assert kwargs['run_identity'] is api.user_identity


def test_the_rule_test_on_unreadable_app_entities_is_refused(api, levels):
    del levels['data-products']

    response = api.http.post('/api/compliance/llm-check/test', json={'rule': APP_RULE})

    assert response.status_code == 403
    assert response.json()['detail']['code'] == 'llm_check_entity_read_required'
    api.manager.test_rule_on_sample.assert_not_called()


def test_the_run_reads_uc_with_the_identity_it_is_given(db_session):
    from src.common.run_identity import RunIdentity

    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='P', rule=PLAIN_RULE, created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db_session.add(policy)
    db_session.flush()
    user_client = MagicMock()
    identity = RunIdentity(lambda: user_client, on_behalf_of_user=True)
    manager = ComplianceManager()
    with patch('src.common.workspace_client.get_workspace_client') as app_client, \
            patch('src.controller.compliance_manager.create_entity_iterator') as iterator:
        iterator.return_value.iterate.return_value = []
        manager.run_policy_inline(db_session, policy=policy, run_identity=identity)

    app_client.assert_not_called()
    assert iterator.call_args.kwargs['workspace_client'] is user_client


def test_a_run_without_the_users_token_fails_with_a_code(db_session):
    from src.common.api_errors import UserTokenRequiredError
    from src.common.run_identity import RunIdentity

    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='P', rule=UC_RULE, created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db_session.add(policy)
    db_session.flush()

    def no_token():
        raise UserTokenRequiredError('sign in')

    run = ComplianceManager().run_policy_inline(
        db_session, policy=policy, run_identity=RunIdentity(no_token, on_behalf_of_user=True),
    )

    assert (run.status, run.error_code) == ('failed', 'user_token_required')


# --- Admin gate: LLM_CHECK rules are saved, run and tested by compliance admins ---

def _payload(rule, name='P'):
    return {
        'name': name, 'description': 'd', 'category': 'Governance', 'severity': 'low',
        'rule': rule, 'is_active': True,
    }


@pytest.fixture
def writer(levels):
    """Write access to compliance, not admin."""
    levels['compliance'] = FeatureAccessLevel.READ_WRITE
    return levels


def _admin_required(response):
    assert response.status_code == 403, response.text
    assert response.json()['detail']['code'] == 'llm_check_admin_required'


def test_creating_an_llm_check_rule_needs_compliance_admin(api, writer):
    _admin_required(api.http.post('/api/compliance/policies', json=_payload(UC_RULE)))
    api.manager.create_policy.assert_not_called()


def test_a_writer_still_creates_rules_without_llm_check(api, writer):
    api.manager.create_policy.return_value = SimpleNamespace(
        id='p1', name='P', description='d', rule=PLAIN_RULE, created_at=None, updated_at=None,
        is_active=True, severity='low', category='Governance',
    )
    response = api.http.post('/api/compliance/policies', json=_payload(PLAIN_RULE))
    assert response.status_code == 200, response.text


PID = str(uuid.uuid4())


def test_changing_a_rule_to_llm_check_needs_compliance_admin(api, writer):
    api.manager.get_policy.return_value = SimpleNamespace(id=PID, name='P', rule=PLAIN_RULE)

    response = api.http.put(
        f'/api/compliance/policies/{PID}', json={**_payload(UC_RULE), 'id': PID},
    )

    _admin_required(response)
    api.manager.update_policy.assert_not_called()


def test_other_edits_of_an_llm_check_policy_are_not_gated(api, writer):
    api.manager.get_policy.return_value = SimpleNamespace(id=PID, name='P', rule=UC_RULE)
    api.manager.update_policy.return_value = CompliancePolicyDb(
        id=PID, name='P', description='d2', rule=UC_RULE, category='Governance',
        severity='low', is_active=False, created_at=datetime.now(), updated_at=datetime.now(),
    )

    edited = {**_payload(UC_RULE), 'description': 'd2', 'is_active': False, 'id': PID}
    assert api.http.put(f'/api/compliance/policies/{PID}', json=edited).status_code == 200


def test_running_an_llm_check_rule_needs_compliance_admin(api, writer):
    _policy(api.manager, UC_RULE)

    _admin_required(api.http.post('/api/compliance/policies/p1/runs', json={}))
    api.manager.run_policy_inline.assert_not_called()


def test_testing_an_llm_check_rule_needs_compliance_admin(api, writer):
    _admin_required(api.http.post('/api/compliance/llm-check/test', json={'rule': UC_RULE}))
    api.manager.test_rule_on_sample.assert_not_called()


def test_saving_a_rule_with_llm_check_in_where_is_refused(api):
    rule = "MATCH (t:table)\nWHERE LLM_CHECK(t.comment, 'x')\nASSERT t.name = 'x'"

    response = api.http.post('/api/compliance/policies', json=_payload(rule))

    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'llm_check_in_where'
    api.manager.create_policy.assert_not_called()


def test_the_rule_test_without_a_workspace_client_answers_503(api):
    error = RuntimeError('no workspace')
    error.error_code = 'workspace_client_unavailable'
    api.manager.test_rule_on_sample.side_effect = error

    response = api.http.post('/api/compliance/llm-check/test', json={'rule': UC_RULE})

    assert response.status_code == 503
