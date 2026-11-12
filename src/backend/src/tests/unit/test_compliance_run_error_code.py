"""A failed compliance run stores a code the UI can translate.

The error text stays the English fallback; errors the app writes itself also
get a stable code and parameters, others (SDK, database) have none.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from unittest.mock import MagicMock, patch

from src.common.compliance_errors import ComplianceRunError, run_error_code
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb
from src.routes.compliance_routes import _run_error_code


def _policy(db, rule):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='Test policy', rule=rule, is_active=True)
    db.add(policy)
    db.flush()
    return policy


def _run(db, policy, iterator=None):
    iterator = iterator or MagicMock(**{'iterate.return_value': iter([])})
    with patch('src.controller.compliance_manager.create_entity_iterator', return_value=iterator), \
            patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()):
        return ComplianceManager().run_policy_inline(db, policy=policy)


def test_a_rule_that_does_not_parse_stores_a_code_and_its_detail(db_session):
    run = _run(db_session, _policy(db_session, 'MATCH (p:data_product) ASSERT'))

    assert run.status == 'failed'
    assert run.error_message.startswith('Failed to parse rule: ')
    assert run.error_code == 'rule_parse_failed'
    assert json.loads(run.error_params)['detail'] in run.error_message


def test_an_app_error_with_a_code_stores_it(db_session):
    iterator = MagicMock()
    iterator.iterate.side_effect = ComplianceRunError(
        'Could not load the tags of data_product entities', 'entity_load_failed',
        entityType='data_product',
    )

    run = _run(db_session, _policy(db_session, "MATCH (p:data_product) ASSERT p.name != ''"), iterator)

    assert run.error_code == 'entity_load_failed'
    assert json.loads(run.error_params) == {'entityType': 'data_product'}


def test_a_coded_error_does_not_pass_the_exception_text_to_the_ui(db_session):
    # The workspace client failed with an SDK error: the run stores the code
    # without parameters, the SDK text only as the stored fallback message.
    policy = _policy(db_session, "MATCH (o:Object) ASSERT o.name != ''")
    with patch('src.common.workspace_client.get_workspace_client',
               side_effect=RuntimeError('cannot get access token from https://internal.example')):
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)

    assert run.status == 'failed'
    assert run.error_code == 'workspace_client_unavailable'
    assert run.error_params is None
    assert _run_error_code(run) == {'error_code': 'workspace_client_unavailable', 'error_params': None}
    assert 'internal.example' in run.error_message


def test_other_errors_keep_only_their_text(db_session):
    iterator = MagicMock()
    iterator.iterate.side_effect = RuntimeError('connection reset by peer')

    run = _run(db_session, _policy(db_session, "MATCH (p:data_product) ASSERT p.name != ''"), iterator)

    assert run.status == 'failed'
    assert run.error_message == 'connection reset by peer'
    assert run.error_code is None and run.error_params is None


def test_a_successful_run_has_no_code(db_session):
    run = _run(db_session, _policy(db_session, "MATCH (p:data_product) ASSERT p.name != ''"))

    assert run.status == 'succeeded'
    assert run.error_code is None and run.error_params is None


def test_the_api_returns_the_code_and_parsed_params():
    run = MagicMock(error_code='rule_parse_failed', error_params='{"detail": "x"}')
    assert _run_error_code(run) == {'error_code': 'rule_parse_failed', 'error_params': {'detail': 'x'}}

    plain = MagicMock(error_code=None, error_params=None)
    assert _run_error_code(plain) == {'error_code': None, 'error_params': None}


def test_errors_without_a_code_are_not_classified():
    assert run_error_code(ValueError('Evaluation error: x')) == (None, None)
    assert run_error_code(RuntimeError('boom')) == (None, None)
