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


# --- the viewer filter fails closed, and covers each Unity Catalog type ---

def _results_as(db, run, viewer=None, obo_error=None):
    import asyncio

    from src.common import workspace_client as wc
    from src.routes import compliance_routes

    obo = ({'side_effect': lambda *a, **k: wc.raise_user_token_required()} if obo_error
           else {'return_value': viewer})
    with patch('src.common.workspace_client.get_obo_workspace_client', **obo):
        return asyncio.run(compliance_routes.get_run_results(
            run.id, request=SimpleNamespace(headers={}), db=db, only_failed=False, _=True,
        ))


def test_a_viewer_without_a_token_gets_no_uc_result_nor_its_reason(db_session):
    run = _run_with_results(db_session)

    body = _results_as(db_session, run, obo_error=True)

    assert [r['object_id'] for r in body['results']] == ['d1']
    assert body['hidden_count'] == 3
    assert 'quotes main' not in json.dumps(body, default=str)


def test_a_listing_that_fails_hides_every_result_it_covers(db_session):
    run = _run_with_results(db_session)
    viewer = MagicMock()
    viewer.tables.list.side_effect = RuntimeError('warehouse down')

    body = _results_as(db_session, run, viewer=viewer)

    assert [r['object_id'] for r in body['results']] == ['d1']
    assert body['hidden_count'] == 3


@pytest.mark.parametrize('object_type, object_id, shown', [
    ('catalog', 'main', True), ('catalog', 'hr', False),
    ('schema', 'main.sales', True), ('schema', 'main.private', False),
    ('schema', 'hr.sales', False),
    ('function', 'main.sales.mask', True), ('function', 'main.sales.secret', False),
    ('volume', 'main.sales.landing', True), ('volume', 'main.sales.private', False),
    # Ids with the wrong number of parts are never shown
    ('table', 'main.orders', False), ('schema', 'main', False),
    ('catalog', 'main.sales', False), ('function', 'main.sales.mask.x', False),
    ('volume', None, False),
])
def test_each_uc_type_is_checked_with_its_own_listing(object_type, object_id, shown):
    from src.common.compliance_result_visibility import ViewerReadChecks

    viewer = MagicMock()
    viewer.catalogs.list.return_value = [SimpleNamespace(name='main')]
    viewer.schemas.list.side_effect = lambda catalog_name: (
        [SimpleNamespace(name='sales')] if catalog_name == 'main' else []
    )
    viewer.functions.list.side_effect = lambda catalog_name, schema_name: (
        [SimpleNamespace(name='mask')] if (catalog_name, schema_name) == ('main', 'sales')
        else []
    )
    viewer.volumes.list.side_effect = lambda catalog_name, schema_name: (
        [SimpleNamespace(name='landing')] if (catalog_name, schema_name) == ('main', 'sales')
        else []
    )

    assert ViewerReadChecks(lambda: viewer).can_read(object_type, object_id) is shown
    viewer.tables.list.assert_not_called()

