"""Run counts per viewer and coded run errors (#1387 review).

- A run's counts and score leave out the results the viewer can't read.
- A failed run's error reaches readers as a code (``run_failed`` without one of
  ours), never as the exception text; the timeline entry carries the code too.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.compliance_errors import public_run_error
from src.common.compliance_result_visibility import ViewerReadChecks
from src.common.uc_table_enrichment import NOT_EVALUATED_CODE
from src.controller.compliance_manager import ComplianceManager, viewer_run_fields
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb, ComplianceRunDb


def _checks(readable_tables):
    """A viewer who lists only ``readable_tables`` in main.sales."""
    ws = MagicMock()
    ws.tables.list.return_value = [SimpleNamespace(name=n) for n in readable_tables]
    return ViewerReadChecks(lambda: ws), ws


def _policy(db, rule="MATCH (p:data_product) ASSERT p.name != ''"):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='p', is_active=True, rule=rule)
    db.add(policy)
    db.flush()
    return policy


def _run_with(db, rows, status='succeeded'):
    """A stored run with ``rows`` of (object_type, object_id, outcome)."""
    success = sum(1 for *_, o in rows if o == 'passed')
    failure = sum(1 for *_, o in rows if o == 'failed')
    run = ComplianceRunDb(
        id=str(uuid.uuid4()), policy_id=_policy(db).id, status=status,
        success_count=success, failure_count=failure,
        score=round(100.0 * success / (success + failure), 2) if success + failure else None,
    )
    db.add(run)
    for object_type, object_id, outcome in rows:
        db.add(ComplianceResultDb(
            id=str(uuid.uuid4()), run_id=run.id, object_type=object_type, object_id=object_id,
            object_name=object_id, passed=outcome == 'passed',
            details_json=(json.dumps({'code': NOT_EVALUATED_CODE, 'params': {}})
                          if outcome == 'not_evaluated' else None),
        ))
    db.flush()
    return run


ROWS = [
    ('table', 'main.sales.orders', 'passed'),
    ('table', 'main.sales.payroll', 'failed'),
    ('table', 'main.sales.salaries', 'not_evaluated'),
    ('data_product', 'p1', 'failed'),
]


def test_counts_and_score_leave_out_what_the_viewer_cannot_read(db_session):
    run = _run_with(db_session, ROWS)
    checks, ws = _checks(['orders'])

    counts = ComplianceManager().viewer_run_counts(db_session, [run], checks)[run.id]

    assert counts == {'success': 1, 'failure': 1, 'not_evaluated': 0, 'hidden': 2}
    fields = viewer_run_fields(run, counts)
    assert (fields['success_count'], fields['failure_count']) == (1, 1)
    # Not the stored 33.33 (1 of 3): payroll is not the viewer's to count
    assert fields['score'] == 50.0
    assert fields['coverage'] == {'evaluated': 2, 'not_evaluated': 0}
    assert fields['hidden_count'] == 2
    ws.tables.list.assert_called_once_with(catalog_name='main', schema_name='sales')


def test_a_viewer_who_reads_everything_gets_the_stored_score(db_session):
    run = _run_with(db_session, ROWS)
    checks, _ = _checks(['orders', 'payroll', 'salaries'])

    fields = viewer_run_fields(
        run, ComplianceManager().viewer_run_counts(db_session, [run], checks)[run.id],
    )

    assert (fields['success_count'], fields['failure_count'], fields['score']) == (1, 2, 33.33)
    assert fields['coverage'] == {'evaluated': 3, 'not_evaluated': 1}
    assert fields['hidden_count'] == 0


def test_a_viewer_who_reads_none_of_the_evaluated_results_gets_no_score(db_session):
    run = _run_with(db_session, [('table', 'main.sales.payroll', 'failed')])
    checks, _ = _checks([])

    fields = viewer_run_fields(
        run, ComplianceManager().viewer_run_counts(db_session, [run], checks)[run.id],
    )

    assert fields['score'] is None and fields['hidden_count'] == 1
    assert (fields['success_count'], fields['failure_count']) == (0, 0)


def test_a_seeded_run_without_results_keeps_its_counts(db_session):
    run = ComplianceRunDb(id=str(uuid.uuid4()), policy_id=_policy(db_session).id,
                          status='succeeded', success_count=8, failure_count=2, score=80.0)
    db_session.add(run)
    db_session.flush()
    checks, _ = _checks([])

    fields = viewer_run_fields(
        run, ComplianceManager().viewer_run_counts(db_session, [run], checks)[run.id],
    )

    assert (fields['success_count'], fields['failure_count'], fields['score']) == (8, 2, 80.0)


def test_a_results_page_skips_hidden_rows_and_counts_every_visible_one(db_session):
    run = _run_with(db_session, ROWS)
    checks, _ = _checks(['orders'])
    manager = ComplianceManager()

    page, total, hidden = manager.viewer_results_page(
        db_session, run_id=run.id, checks=checks, offset=0, limit=1,
    )
    rest, _, _ = manager.viewer_results_page(
        db_session, run_id=run.id, checks=checks, offset=1, limit=10,
    )
    failed, failed_total, failed_hidden = manager.viewer_results_page(
        db_session, run_id=run.id, checks=checks, only_failed=True,
    )

    assert (len(page), total, hidden) == (1, 2, 2)
    assert {r.object_id for r in page + rest} == {'main.sales.orders', 'p1'}
    # Failures only: payroll hidden; salaries not evaluated, so not a failure
    assert [r.object_id for r in failed] == ['p1']
    assert (failed_total, failed_hidden) == (1, 1)


@pytest.mark.parametrize('status, code, params, expected', [
    ('failed', 'entities_load_failed', {'entityType': 'x'},
     ('entities_load_failed', {'entityType': 'x'})),
    # An SDK's own code, or none: the generic code, and no parameters
    ('failed', 'PERMISSION_DENIED', {'detail': 'main.secret.payroll'}, ('run_failed', None)),
    ('failed', None, None, ('run_failed', None)),
    ('succeeded', None, None, (None, None)),
])
def test_public_run_error(status, code, params, expected):
    assert public_run_error(status, code, params) == expected


def test_the_timeline_entry_of_a_failed_run_carries_the_code_not_the_text(db_session):
    policy = _policy(db_session)
    with patch('src.controller.compliance_manager.parse_rule',
               side_effect=RuntimeError('cannot reach db.internal.example')), \
            patch('src.controller.change_log_manager.change_log_manager') as change_log:
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)

    assert run.status == 'failed'
    details = change_log.log_change_with_details.call_args.kwargs['details']
    assert details['error_code'] == 'run_failed'
    assert 'internal.example' not in json.dumps(details)

