"""A policy without a scored run has no score, not 0 % (#1387 review).

A run that failed or evaluated nothing has no score. The policy list and the
stats use the latest run with a score; a policy that has none is left out of
the overall compliance and is not a critical issue, and the compliance-checks
job prints "no score" for it.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import src.workflows.compliance_checks.compliance_checks as job
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceRunDb


def _policy(db, name, severity='medium'):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=name, is_active=True, severity=severity,
        rule="MATCH (p:data_product) ASSERT p.name != ''",
    )
    db.add(policy)
    db.flush()
    return policy


def _run(db, policy, status, success, failure, score, minutes_ago):
    db.add(ComplianceRunDb(
        id=str(uuid.uuid4()), policy_id=policy.id, status=status,
        success_count=success, failure_count=failure, score=score,
        started_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    ))
    db.flush()


def test_policies_without_a_scored_run_have_no_score_and_stay_out_of_the_stats(db_session):
    scored = _policy(db_session, 'scored')
    _run(db_session, scored, 'succeeded', 7, 3, 70.0, minutes_ago=2)
    _run(db_session, scored, 'failed', 0, 0, 0.0, minutes_ago=1)  # keeps the 70
    failed_only = _policy(db_session, 'failed only', severity='critical')
    _run(db_session, failed_only, 'failed', 2, 0, 0.0, minutes_ago=1)
    _policy(db_session, 'never run', severity='critical')

    data = ComplianceManager().get_policies_with_stats(db_session)

    by_name = {p['name']: p['compliance'] for p in data['policies']}
    assert by_name == {'scored': 70.0, 'failed only': None, 'never run': None}
    # Not (70 + 0 + 0) / 3: the unscored policies are not counted as 0
    assert data['stats']['overall_compliance'] == 70.0
    # A critical policy without a score is not an issue found
    assert data['stats']['critical_issues'] == 0
    assert data['stats']['active_policies'] == 3


def test_overall_compliance_is_none_when_no_policy_has_a_score(db_session):
    policy = _policy(db_session, 'empty')
    _run(db_session, policy, 'succeeded', 0, 0, 0.0, minutes_ago=1)

    stats = ComplianceManager().get_compliance_stats(db_session)

    assert stats['overall_compliance'] is None
    assert stats['critical_issues'] == 0


def test_a_critical_policy_scored_below_70_is_a_critical_issue(db_session):
    policy = _policy(db_session, 'low', severity='critical')
    _run(db_session, policy, 'succeeded', 1, 3, 25.0, minutes_ago=1)

    assert ComplianceManager().get_compliance_stats(db_session)['critical_issues'] == 1


def test_the_job_prints_no_score_for_a_run_without_one(db_session, capsys):
    policy = _policy(db_session, 'matches nothing')
    iterator = MagicMock(**{'iterate.return_value': iter([])})
    with patch('src.controller.compliance_manager.create_entity_iterator', return_value=iterator):
        result = job.run_policy(
            db_session, {'id': policy.id, 'name': policy.name}, ComplianceManager(), None,
        )

    assert result['status'] == 'succeeded' and result['score'] is None
    assert 'Score: no score' in capsys.readouterr().out


def test_the_job_lists_failed_and_low_runs_for_attention_not_unscored_ones():
    assert job._needs_attention({'status': 'error'})
    assert job._needs_attention({'status': 'failed', 'score': None})
    assert job._needs_attention({'status': 'succeeded', 'score': 50.0})
    assert not job._needs_attention({'status': 'succeeded', 'score': 90.0})
    # None < 70 would raise a TypeError in the job's summary
    assert not job._needs_attention({'status': 'succeeded', 'score': None})
    assert job._score_text(None) == 'no score'
    assert job._score_text(85.0) == '85.0%'


def test_the_api_models_carry_no_score_as_none():
    from src.models.compliance import CompliancePolicy, ComplianceRun

    run = ComplianceRun(
        id='r1', policy_id='p1', status='failed', started_at=datetime.utcnow(),
        success_count=0, failure_count=0, score=None,
    )
    policy = CompliancePolicy(
        id=uuid.uuid4(), name='p', description='d', rule='MATCH (p:data_product)',
        compliance=None,
    )

    assert run.score is None and policy.compliance is None
    # Without a value, neither claims a 0 % score
    assert ComplianceRun(
        id='r2', policy_id='p1', status='running', started_at=datetime.utcnow(),
        success_count=0, failure_count=0,
    ).score is None
    assert CompliancePolicy(
        id=uuid.uuid4(), name='p', description='d', rule='MATCH (p:data_product)',
    ).compliance is None



def test_the_trend_averages_only_the_runs_that_have_a_score(db_session):
    scored = _policy(db_session, 'scored')
    other = _policy(db_session, 'other')
    _run(db_session, scored, 'succeeded', 8, 2, 80.0, minutes_ago=0)
    _run(db_session, other, 'succeeded', 6, 4, 60.0, minutes_ago=0)
    # Stored as 0.0, but without a score: a failed run and one that evaluated nothing
    _run(db_session, scored, 'failed', 2, 0, 0.0, minutes_ago=0)
    _run(db_session, other, 'succeeded', 0, 0, 0.0, minutes_ago=0)

    trend = ComplianceManager().get_compliance_trend(db_session, days=2)

    # (80 + 60) / 2, not (80 + 60 + 0 + 0) / 4
    assert trend[-1]['compliance'] == 70.0
    assert trend[0]['compliance'] == 0.0  # no run yesterday

