"""A metric view's baseline and its drift state (#1124, module 3).

The first definition Ontos parses becomes the baseline (not approved: approvals
come with change requests); each read compares the normalized definition with
it. A change Unity Catalog makes to the stored text is not drift; a changed
expression is, and the asset's owners are told once per change.
"""
import json
import uuid
from unittest.mock import patch

import pytest

from src.common.metric_views import parse_metric_view_definition
from src.controller.metric_view_baselines_manager import (
    DRIFT_DESCRIPTION_KEY, DRIFT_TITLE_KEY, MetricViewBaselinesManager,
)
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.metric_view_baselines import MetricViewBaselineDb
from src.db_models.notifications import NotificationDb
from src.repositories.metric_view_baselines_repository import metric_view_baselines_repo

FQN = 'main.sales.orders_mv'
SPEC = """\
version: 1.1
source: main.sales.orders
fields:
  - name: Region
    expr: region
measures:
  - name: Total Revenue
    expr: SUM(amount)
    display_name: Revenue
"""
# As Unity Catalog stores it: `dimensions`, no display_name, other whitespace
STORED = SPEC.replace('fields:', 'dimensions:').replace('    display_name: Revenue\n', '') \
    .replace('expr: SUM(amount)', 'expr: "  SUM(amount) "')
CHANGED = SPEC.replace('SUM(amount)', 'SUM(net_amount)')
CHANGED_AGAIN = SPEC.replace('SUM(amount)', 'SUM(gross_amount)')
OWNER = 'owner@example.com'


@pytest.fixture
def asset_id(db_session):
    role = db_session.query(BusinessRoleDb).filter_by(name='Data Owner').first()
    if role is None:
        role = BusinessRoleDb(id=uuid.uuid4(), name='Data Owner')
        db_session.add(role)
        db_session.flush()
    asset_id = uuid.uuid4()
    db_session.add(BusinessOwnerDb(
        id=uuid.uuid4(), object_type='asset', object_id=str(asset_id),
        user_email=OWNER, role_id=role.id, is_active=True,
    ))
    db_session.flush()
    return asset_id


def _check(db, definition, asset_id, fqn=FQN, user='reader@example.com'):
    return MetricViewBaselinesManager(db).check(
        fqn, parse_metric_view_definition(definition), asset_id=asset_id, user_email=user,
    )


def _drift_notices(db):
    return [
        n for n in db.query(NotificationDb).all()
        if json.loads(n.data or '{}').get('i18n', {}).get('title') == DRIFT_TITLE_KEY
    ]


def test_the_first_read_records_an_unapproved_baseline_in_sync(db_session, asset_id):
    baseline, drift = _check(db_session, SPEC, asset_id)

    assert drift.state == 'in_sync'
    assert drift.current_digest == baseline.digest
    assert drift.last_checked_at is not None
    # Recorded, not approved: approvals come with change requests
    assert baseline.approved_at is None and baseline.request_id is None
    assert baseline.recorded_at is not None
    row = db_session.query(MetricViewBaselineDb).one()
    assert row.metric_view_fqn == FQN
    assert row.created_by == 'reader@example.com'
    assert [m['name'] for m in row.definition['measures']] == ['Total Revenue']
    assert 'display_name' not in row.definition['measures'][0]
    assert _drift_notices(db_session) == []


def test_unity_catalogs_rewrite_of_the_stored_text_is_not_drift(db_session, asset_id):
    _check(db_session, SPEC, asset_id)

    _, drift = _check(db_session, STORED, asset_id)

    assert drift.state == 'in_sync'
    assert _drift_notices(db_session) == []


def test_a_changed_expression_is_drift_notified_once_to_the_owners(db_session, asset_id):
    baseline, _ = _check(db_session, SPEC, asset_id)

    _, drift = _check(db_session, CHANGED, asset_id)
    _, again = _check(db_session, CHANGED, asset_id)

    assert drift.state == 'drifted' and again.state == 'drifted'
    assert drift.current_digest != baseline.digest
    notices = _drift_notices(db_session)
    assert [n.recipient for n in notices] == [OWNER]
    notice = notices[0]
    assert notice.type == 'warning'
    assert notice.link == f'/assets/{asset_id}'
    assert json.loads(notice.data)['i18n'] == {
        'title': DRIFT_TITLE_KEY, 'description': DRIFT_DESCRIPTION_KEY,
        'params': {'fqn': FQN},
    }
    # The baseline itself is never changed by drift
    assert db_session.query(MetricViewBaselineDb).one().digest == baseline.digest


def test_each_new_change_is_notified_and_a_revert_is_back_in_sync(db_session, asset_id):
    _check(db_session, SPEC, asset_id)
    _check(db_session, CHANGED, asset_id)

    _, other = _check(db_session, CHANGED_AGAIN, asset_id)
    assert other.state == 'drifted'
    assert len(_drift_notices(db_session)) == 2

    _, reverted = _check(db_session, STORED, asset_id)
    assert reverted.state == 'in_sync'
    assert db_session.query(MetricViewBaselineDb).one().drift_state == 'in_sync'
    assert len(_drift_notices(db_session)) == 2


@pytest.mark.parametrize('unreadable', ['not: [valid', '', 'x' * (256 * 1024 + 1)])
def test_an_unparseable_definition_is_unknown_and_keeps_the_baseline(
    db_session, asset_id, unreadable
):
    baseline, _ = _check(db_session, SPEC, asset_id)
    _check(db_session, CHANGED, asset_id)

    kept, drift = _check(db_session, unreadable, asset_id)

    assert drift.state == 'unknown'
    assert drift.current_digest is None
    assert kept.digest == baseline.digest
    row = db_session.query(MetricViewBaselineDb).one()
    assert row.drift_state == 'unknown'
    # Reading the same drifted definition again is not a new change
    _, back = _check(db_session, CHANGED, asset_id)
    assert back.state == 'drifted'
    assert len(_drift_notices(db_session)) == 1


def test_no_baseline_is_recorded_from_an_unparseable_definition(db_session, asset_id):
    baseline, drift = _check(db_session, 'not: [valid', asset_id)

    assert baseline is None
    assert drift.state == 'unknown' and drift.last_checked_at is None
    assert db_session.query(MetricViewBaselineDb).count() == 0


def test_the_baseline_is_keyed_on_the_lower_cased_fqn(db_session, asset_id):
    _check(db_session, SPEC, asset_id, fqn='Main.Sales.Orders_MV')

    _, drift = _check(db_session, CHANGED, asset_id, fqn=FQN)

    assert drift.state == 'drifted'
    assert db_session.query(MetricViewBaselineDb).count() == 1


def test_an_asset_without_owners_drifts_without_notifications(db_session, asset_id):
    # asset_id has an owner (and its flush opens SQLite's transaction before the
    # savepoints: pysqlite would otherwise run them outside the test's rollback)
    lonely = uuid.uuid4()
    _check(db_session, SPEC, lonely)

    _, drift = _check(db_session, CHANGED, lonely)

    assert drift.state == 'drifted'
    assert _drift_notices(db_session) == []


def test_a_failing_check_is_unknown_and_does_not_raise(db_session, asset_id):
    _check(db_session, SPEC, asset_id)

    with patch.object(metric_view_baselines_repo, 'record_observation',
                      side_effect=RuntimeError('database is gone')):
        baseline, drift = _check(db_session, CHANGED, asset_id)

    assert baseline is None and drift.state == 'unknown'
    # The failed check's savepoint is rolled back; the session still works
    assert db_session.query(MetricViewBaselineDb).one().drift_state == 'in_sync'


def test_a_baseline_recorded_concurrently_is_reused(db_session, asset_id):
    first = metric_view_baselines_repo.create_if_absent(
        db_session, fqn=FQN, definition={'a': 1}, digest='d' * 64,
        checked_at=None, created_by=None,
    )

    again = metric_view_baselines_repo.create_if_absent(
        db_session, fqn=FQN, definition={'b': 2}, digest='e' * 64,
        checked_at=None, created_by=None,
    )

    assert again.id == first.id and again.digest == 'd' * 64
    assert db_session.query(MetricViewBaselineDb).count() == 1
