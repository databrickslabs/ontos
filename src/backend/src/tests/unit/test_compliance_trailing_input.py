"""A rule with trailing input is refused when it is saved, and flagged when it runs (#1148).

``parse_rule`` stops after the clauses it recognises. Anything left over used
to be dropped, so a rule could be saved and run while checking less than its
author wrote. Saving a new or changed rule now refuses it with a coded error;
a stored rule keeps running, and its run carries a coded warning.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.common.api_errors import CodedValueError
from src.common.compliance_dsl import RuleTrailingInputError, parse_rule
from src.common.compliance_entities import validate_rule
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb
from src.models.compliance import CompliancePolicy, CompliancePolicyCreate
from src.routes import compliance_routes

# The three cases of the issue: (rule, line, column, text)
CASES = [
    ('MATCH (obj:table)\nASSERT obj.name = "x" IS NOT NULL', 2, 23, 'IS'),
    ('MATCH (obj:table)\nASSERT obj.name = "x"\nBOGUS tokens here', 3, 1, 'BOGUS'),
    ('MATCH (obj:table) ASSERT obj.name = "x" ON_FAIL FAIL "m" )', 1, 58, ')'),
]
IDS = ['is_not_null', 'stray_line', 'stray_paren']
COMPLETE = 'MATCH (obj:table) ASSERT obj.name = "x" ON_FAIL FAIL "m"'


@pytest.mark.parametrize('rule,line,column,text', CASES, ids=IDS)
def test_strict_parse_refuses_trailing_input_with_a_code(rule, line, column, text):
    with pytest.raises(RuleTrailingInputError) as e:
        parse_rule(rule, strict=True)

    assert isinstance(e.value, CodedValueError)
    assert e.value.code == 'rule_trailing_input'
    assert e.value.params == {'line': line, 'column': column, 'text': text}
    assert f'line {line}, column {column}' in str(e.value)


@pytest.mark.parametrize('rule,line,column,text', CASES, ids=IDS)
def test_the_default_parse_still_ignores_it_and_reports_it(rule, line, column, text):
    parsed = parse_rule(rule)

    assert parsed['trailing_input'] == {'line': line, 'column': column, 'text': text}


def test_a_complete_rule_has_no_trailing_input():
    assert parse_rule(COMPLETE, strict=True)['trailing_input'] is None


def test_strict_parse_keeps_the_error_of_a_rule_that_does_not_parse():
    with pytest.raises(ValueError, match='Failed to parse rule'):
        parse_rule('MATCH (p:data_product) ASSERT', strict=True)


# --- Save time ---

def _create(db, rule):
    return compliance_routes.create_policy(
        request=MagicMock(client=None), db=db, audit_manager=MagicMock(), current_user=None,
        policy=CompliancePolicyCreate(name='P', description='d', rule=rule), _=True,
    )


async def _update(db, policy, rule, **fields):
    data = {'name': 'P', 'description': 'd', 'is_active': True, **fields}
    return await compliance_routes.update_policy(
        policy_id=policy.id, request=MagicMock(client=None), db=db, audit_manager=MagicMock(),
        current_user=None, policy=CompliancePolicy(id=policy.id, rule=rule, **data), _=True,
    )


@pytest.mark.parametrize('rule,line,column,text', CASES, ids=IDS)
def test_validate_rule_refuses_trailing_input(rule, line, column, text):
    with pytest.raises(RuleTrailingInputError):
        validate_rule(rule)


@pytest.mark.asyncio
@pytest.mark.parametrize('rule,line,column,text', CASES, ids=IDS)
async def test_create_refuses_trailing_input_with_its_code(db_session, rule, line, column, text):
    with pytest.raises(HTTPException) as e:
        await _create(db_session, rule)

    assert e.value.status_code == 422
    cause = e.value.__context__
    assert isinstance(cause, CodedValueError)
    assert (cause.code, cause.params) == (
        'rule_trailing_input', {'line': line, 'column': column, 'text': text},
    )
    assert e.value.detail == str(cause)
    assert db_session.query(CompliancePolicyDb).filter_by(rule=rule).count() == 0


@pytest.mark.asyncio
async def test_update_refuses_a_changed_rule_with_trailing_input(db_session):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='P', description='d', rule=COMPLETE)
    db_session.add(policy)
    db_session.flush()

    with pytest.raises(HTTPException) as e:
        await _update(db_session, policy, CASES[0][0])

    assert e.value.status_code == 422
    db_session.refresh(policy)
    assert policy.rule == COMPLETE


@pytest.mark.asyncio
async def test_a_stored_rule_with_trailing_input_can_still_be_renamed_and_disabled(db_session):
    stored = CASES[0][0]
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='Old', description='d', rule=stored)
    db_session.add(policy)
    db_session.flush()

    body = await _update(db_session, policy, stored, name='Renamed', is_active=False)

    assert body['warnings'] == []
    db_session.refresh(policy)
    assert (policy.name, policy.is_active, policy.rule) == ('Renamed', False, stored)


# --- Run time ---

def _policy(db, rule):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=f'Stored {uuid.uuid4().hex[:6]}', rule=rule, is_active=True,
    )
    db.add(policy)
    db.flush()
    return policy


def _run(db, policy):
    iterator = MagicMock(**{'iterate.return_value': iter([])})
    with patch('src.controller.compliance_manager.create_entity_iterator', return_value=iterator), \
            patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()):
        return ComplianceManager().run_policy_inline(db, policy=policy)


def test_a_stored_rule_with_trailing_input_still_runs_and_the_run_has_a_warning(db_session):
    run = _run(db_session, _policy(db_session, CASES[0][0]))

    assert run.status == 'succeeded'
    assert run.error_message is None
    assert run.error_code == 'rule_trailing_input'
    assert json.loads(run.error_params) == {'line': 2, 'column': 23, 'text': 'IS'}
    # The API shows it as a warning, not as an error
    assert compliance_routes._run_codes(run) == {
        'error_code': None, 'error_params': None,
        'warning_code': 'rule_trailing_input',
        'warning_params': {'line': 2, 'column': 23, 'text': 'IS'},
    }


def test_a_complete_rule_has_no_run_warning(db_session):
    run = _run(db_session, _policy(db_session, COMPLETE))

    assert run.status == 'succeeded'
    assert run.error_code is None and run.error_params is None
    assert compliance_routes._run_codes(run)['warning_code'] is None


def test_a_failed_run_still_reports_its_error_not_a_warning(db_session):
    run = _run(db_session, _policy(db_session, 'MATCH (p:data_product) ASSERT'))

    codes = compliance_routes._run_codes(run)
    assert codes['error_code'] == 'rule_parse_failed'
    assert codes['warning_code'] is None
