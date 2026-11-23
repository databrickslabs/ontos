"""The compliance-checks job records and shows the warning of a finished run (#1148).

The job runs each policy through ``ComplianceManager.run_policy_inline``, so a
stored rule with trailing input gets the same ``rule_trailing_input`` warning
on its run as a run started from the UI; the job also prints it and returns it
in the policy's result.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from unittest.mock import MagicMock, patch

import src.workflows.compliance_checks.compliance_checks as job
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceRunDb

TRAILING = 'MATCH (obj:table)\nASSERT obj.name = "x" IS NOT NULL'
COMPLETE = 'MATCH (obj:table) ASSERT obj.name = "x" ON_FAIL FAIL "m"'


def _run_job_policy(db, rule, entities=()):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='Stored', rule=rule, is_active=True)
    db.add(policy)
    db.flush()
    iterator = MagicMock(**{'iterate.return_value': iter(entities)})
    with patch('src.controller.compliance_manager.create_entity_iterator', return_value=iterator), \
            patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()):
        return job.run_policy(db, {'id': policy.id, 'name': 'Stored'}, ComplianceManager(), None)


def test_a_job_run_records_and_returns_the_warning(db_session, capsys):
    result = _run_job_policy(db_session, TRAILING)

    params = {'line': 2, 'column': 23, 'text': 'IS'}
    assert result['status'] == 'succeeded'
    assert result['warning'] == {'code': 'rule_trailing_input', 'params': params}
    run = db_session.get(ComplianceRunDb, result['run_id'])
    assert run.warning_code == 'rule_trailing_input'
    assert json.loads(run.warning_params) == params
    assert run.error_code is None
    assert 'WARNING: rule_trailing_input' in capsys.readouterr().out


def test_a_job_run_of_a_complete_rule_has_no_warning(db_session, capsys):
    # With an entity: a run that matches none has the no_entities_matched warning
    table = {'type': 'table', 'id': 'main.s.x', 'name': 'x'}
    result = _run_job_policy(db_session, COMPLETE, entities=[table])

    assert result['status'] == 'succeeded'
    assert result['warning'] is None
    assert 'WARNING' not in capsys.readouterr().out
