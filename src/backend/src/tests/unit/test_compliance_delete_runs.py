"""ComplianceManager.delete_runs removes every run of the given policies (#1044).

Clearing the demo data deleted only the runs listed in the demo packs; a run
started afterwards kept its policy from being deleted.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb, ComplianceRunDb


def _policy(db):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=f'policy-{uuid.uuid4().hex[:8]}',
        rule="MATCH (p:data_product) ASSERT p.status = 'active'",
        category='Governance', severity='low', is_active=True,
    )
    db.add(policy)
    db.flush()
    return policy


def _run_with_results(db, policy, results=2):
    run = ComplianceRunDb(id=str(uuid.uuid4()), policy_id=policy.id, status='succeeded')
    db.add(run)
    db.flush()
    for _ in range(results):
        db.add(ComplianceResultDb(
            id=str(uuid.uuid4()), run_id=run.id, object_type='data_product',
            object_id=str(uuid.uuid4()), passed=True,
        ))
    db.flush()
    return run


def _counts(db, policy):
    runs = db.query(ComplianceRunDb).filter(ComplianceRunDb.policy_id == policy.id).count()
    results = (
        db.query(ComplianceResultDb).join(ComplianceRunDb)
        .filter(ComplianceRunDb.policy_id == policy.id).count()
    )
    return runs, results


def test_deletes_every_run_and_result_of_the_policies(db_session):
    demo, other = _policy(db_session), _policy(db_session)
    _run_with_results(db_session, demo)
    _run_with_results(db_session, demo, results=1)
    _run_with_results(db_session, other)

    counts = ComplianceManager().delete_runs(db_session, policy_ids=[demo.id])

    assert counts == {'compliance_results': 3, 'compliance_runs': 2}
    assert _counts(db_session, demo) == (0, 0)
    assert _counts(db_session, other) == (1, 2)


def test_no_policies_deletes_nothing(db_session):
    policy = _policy(db_session)
    _run_with_results(db_session, policy)

    assert ComplianceManager().delete_runs(db_session, policy_ids=[]) == {}
    assert _counts(db_session, policy) == (1, 2)
