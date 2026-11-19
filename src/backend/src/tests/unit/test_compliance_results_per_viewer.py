"""#1486 review: run results per viewer, no score without evaluated entities,
only_failed without the not-evaluated results."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb, ComplianceRunDb
from src.repositories.compliance_repository import compliance_result_repo


def _run_with_results(db):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='p', is_active=True, rule='x')
    run = ComplianceRunDb(id=str(uuid.uuid4()), policy_id=policy.id, status='succeeded',
                          success_count=1, failure_count=1, score=50.0, not_evaluated_count=1)
    db.add_all([policy, run])
    for object_type, object_id, passed, not_evaluated in (
        ('table', 'main.sales.orders', True, False),
        ('table', 'hr.private.salaries', False, False),
        ('table', 'main.sales.raw', False, True),
        ('domain', 'd1', False, False),
    ):
        db.add(ComplianceResultDb(
            id=str(uuid.uuid4()), run_id=run.id, object_type=object_type,
            object_id=object_id, object_name=object_id.split('.')[-1], passed=passed,
            not_evaluated=not_evaluated,
            details_json=json.dumps({'llm_checks': [{'reason': f'quotes {object_id}'}]}),
        ))
    db.flush()
    return run


def test_only_failed_leaves_out_the_not_evaluated_results(db_session):
    run = _run_with_results(db_session)

    failed = compliance_result_repo.list_for_run(db_session, run_id=run.id, only_failed=True)

    assert sorted(r.object_id for r in failed) == ['d1', 'hr.private.salaries']


def test_results_and_reasons_of_tables_the_viewer_cannot_read_are_not_returned(db_session):
    """A runs an LLM_CHECK rule; B, without a grant on hr, doesn't get its reason."""
    import asyncio

    from src.routes import compliance_routes

    run = _run_with_results(db_session)
    viewer = MagicMock()
    viewer.tables.list.side_effect = lambda catalog_name, schema_name: (
        [SimpleNamespace(name='orders'), SimpleNamespace(name='raw')]
        if (catalog_name, schema_name) == ('main', 'sales') else []
    )
    with patch('src.common.workspace_client.get_obo_workspace_client', return_value=viewer):
        body = asyncio.run(compliance_routes.get_run_results(
            run.id, request=SimpleNamespace(headers={'x-forwarded-access-token': 't'}),
            db=db_session, only_failed=False, _=True,
        ))

    assert sorted(r['object_id'] for r in body['results']) == [
        'd1', 'main.sales.orders', 'main.sales.raw',
    ]
    assert 'salaries' not in json.dumps(body, default=str)
    assert body['hidden_count'] == 1
    assert body['run']['score'] == 50.0
    assert body['run']['coverage'] == {'evaluated': 2, 'not_evaluated': 1}


@pytest.mark.parametrize('status, success, failure, expected', [
    ('succeeded', 0, 0, None),  # nothing evaluated
    ('failed', 2, 0, None),  # a failed run has no score
    ('succeeded', 1, 1, 50.0),
])
def test_a_run_without_evaluated_entities_or_that_failed_has_no_score(
    status, success, failure, expected,
):
    from src.controller.compliance_manager import run_score_fields

    run = SimpleNamespace(status=status, success_count=success, failure_count=failure,
                          score=50.0 if expected else 0.0, not_evaluated_count=3)

    assert run_score_fields(run)['score'] == expected
