"""Bulk maturity evaluation of table and view assets (#1316 slice).

The per-asset evaluator is replaced by a fake that returns a chosen level, no level,
nothing (asset not found) or raises. The database is the test session; the worker
threads of a run use the same session, one batch at a time.
"""
import json
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from src.controller import maturity_bulk_evaluator as bulk
from src.controller.entity_dict_builder import UnsupportedMaturityAssetTypeError
from src.db_models.app_settings import AppSettingDb
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.maturity import MaturityLevelDb, MaturitySnapshotDb


@pytest.fixture(autouse=True)
def _no_run_in_memory():
    bulk._current = None
    yield
    bulk._current = None


@contextmanager
def _same_session(db):
    yield db


class _Report:
    def __init__(self, order, stored=True):
        self.achieved_level_order = order
        self.stored = stored


class _NotStored:
    """An evaluation that stored nothing (unreadable table, uncertain result)."""

    def __init__(self, order):
        self.order = order


class _FakeEvaluator:
    """outcomes: asset id -> level order, None (no level), 'missing', or an exception."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def evaluate(self, db, *, entity_type, entity_id, persist=True, evaluated_by=None):
        self.calls.append(entity_id)
        outcome = self.outcomes.get(entity_id, 1)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == "missing":
            return None
        if isinstance(outcome, _NotStored):
            return _Report(outcome.order, stored=False)
        return _Report(outcome)


def _type(db, name):
    existing = db.query(AssetTypeDb).filter_by(name=name).first()
    if existing:
        return existing
    asset_type = AssetTypeDb(id=uuid.uuid4(), name=name)
    db.add(asset_type)
    db.flush()
    return asset_type


def _asset(db, location, type_name="Table"):
    asset = AssetDb(
        id=uuid.uuid4(), name=location.split(".")[-1],
        asset_type_id=_type(db, type_name).id, platform="databricks",
        location=location, status="active",
    )
    db.add(asset)
    db.flush()
    return str(asset.id)


def _level(db, order, name, entity_type="Asset"):
    db.add(MaturityLevelDb(level_order=order, name=name, entity_type=entity_type))
    db.flush()


def _snapshot(db, asset_id, order, *, minutes_from_now):
    db.add(MaturitySnapshotDb(
        entity_type="Asset", entity_id=asset_id, achieved_level_order=order,
        achieved_level_name=f"level {order}", total_levels=2,
        evaluated_at=datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now),
    ))
    db.flush()


def _run(db, scope, evaluator, *, max_workers=1, batch_size=100):
    snapshot = bulk.start_run(scope, started_by="admin@example.com",
                              max_workers=max_workers, batch_size=batch_size)
    bulk.execute_run(snapshot["id"], scope, evaluated_by="admin@example.com",
                     session_factory=lambda: _same_session(db),
                     evaluator_factory=lambda: evaluator)
    return bulk.get_latest_run(session_factory=lambda: _same_session(db))


def _bulk_scope(**kwargs):
    return bulk.normalize_scope(kwargs.pop("catalog", "bulk"), kwargs.pop("schema_name", None),
                                kwargs.pop("asset_types", None))


# --- Scope -----------------------------------------------------------------------------

def test_the_scope_is_normalised_and_checked():
    scope = bulk.normalize_scope(" main ", " sales ", ["view", "Table", "VIEW"])

    assert (scope.catalog, scope.schema_name, scope.asset_types) == (
        "main", "sales", ("View", "Table"),
    )
    # The default scope is every asset type the maturity levels apply to
    assert bulk.normalize_scope(None, None, None).asset_types == ("Table", "View", "Metric View")
    for args in [(None, "sales", None), ("main.x", None, None), ("main", None, ["Dashboard"])]:
        with pytest.raises(bulk.MaturityBulkScopeError) as info:
            bulk.normalize_scope(*args)
        assert info.value.code == "maturity_bulk_scope_invalid"


def test_the_asset_type_scope_error_names_metric_views():
    with pytest.raises(bulk.MaturityBulkScopeError) as info:
        bulk.normalize_scope("main", None, ["Dashboard"])

    assert str(info.value) == "Maturity levels apply to table, view and metric view assets."


def test_selection_follows_the_scope_and_the_table_and_view_types(db_session):
    orders = _asset(db_session, "bulk.sales.orders")
    revenue = _asset(db_session, "bulk.sales.revenue", type_name="View")
    upper = _asset(db_session, "Bulk.Sales.Upper")
    finance = _asset(db_session, "bulk.finance.gl")
    other = _asset(db_session, "bulkx.sales.orders")
    dashboard = _asset(db_session, "bulk.sales.board", type_name="Dashboard")
    created = {orders, revenue, upper, finance, other, dashboard}

    def selected(scope):
        return set(bulk.select_asset_ids(db_session, scope)) & created

    assert selected(_bulk_scope()) == {orders, revenue, upper, finance}
    assert selected(_bulk_scope(schema_name="sales")) == {orders, revenue, upper}
    assert selected(_bulk_scope(asset_types=["View"])) == {revenue}
    assert other not in selected(_bulk_scope())  # "bulkx." is not in the "bulk" catalog


# --- Run -------------------------------------------------------------------------------

def test_a_run_counts_evaluated_changed_and_skipped_with_reasons(db_session):
    _level(db_session, 1, "Prerequisite")
    _level(db_session, 2, "1 star")
    changed_up = _asset(db_session, "bulk.sales.up")
    first_level = _asset(db_session, "bulk.sales.first")
    done_meanwhile = _asset(db_session, "bulk.sales.done", type_name="View")
    gone = _asset(db_session, "bulk.sales.gone")
    unsupported = _asset(db_session, "bulk.sales.types")
    _snapshot(db_session, changed_up, 1, minutes_from_now=-30)
    # Evaluated after the run started (a retry, a double request): not evaluated again
    _snapshot(db_session, done_meanwhile, 1, minutes_from_now=5)
    evaluator = _FakeEvaluator({
        changed_up: 2,
        first_level: 1,
        gone: "missing",
        unsupported: UnsupportedMaturityAssetTypeError("no", assetType="Dashboard"),
    })

    final = _run(db_session, _bulk_scope(), evaluator)

    assert final["state"] == "completed"
    assert final["finished_at"] is not None
    assert (final["total"], final["processed"]) == (5, 5)
    assert final["evaluated"] == 2
    assert final["changed"] == 2  # up: 1 -> 2; first: none -> 1
    assert final["skipped"] == {
        "maturity_bulk_skipped_evaluated_in_run": 1,
        "maturity_bulk_skipped_not_found": 1,
        "maturity_bulk_skipped_asset_type": 1,
    }
    assert final["error_count"] == 0
    assert done_meanwhile not in evaluator.calls
    assert sorted(evaluator.calls) == sorted([changed_up, first_level, gone, unsupported])


def test_an_evaluation_failure_is_counted_with_a_code_and_no_exception_text(db_session):
    _level(db_session, 1, "Prerequisite")
    failing = _asset(db_session, "bulk.sales.failing")
    fine = _asset(db_session, "bulk.sales.fine")
    evaluator = _FakeEvaluator({failing: RuntimeError("secret database detail")})

    final = _run(db_session, _bulk_scope(), evaluator)

    assert final["state"] == "completed"
    assert final["evaluated"] == 1
    assert final["error_count"] == 1
    assert final["errors"] == [{"asset_id": failing, "code": "maturity_bulk_evaluation_failed",
                                "params": {}}]
    assert "secret database detail" not in json.dumps(final)
    assert fine in evaluator.calls


def test_without_asset_levels_every_asset_is_counted_and_none_is_evaluated(db_session):
    _level(db_session, 1, "Trusted", entity_type="DataProduct")
    _asset(db_session, "bulk.sales.a")
    _asset(db_session, "bulk.sales.b")
    evaluator = _FakeEvaluator({})

    final = _run(db_session, _bulk_scope(), evaluator)

    assert final["total"] == 2
    assert final["skipped"] == {"maturity_bulk_skipped_no_levels": 2}
    assert evaluator.calls == []


def test_one_run_at_a_time_and_a_new_one_after_it_ends(db_session):
    _level(db_session, 1, "Prerequisite")
    scope = _bulk_scope()
    first = bulk.start_run(scope, started_by="a@example.com")

    with pytest.raises(bulk.MaturityBulkRunInProgressError) as info:
        bulk.start_run(scope, started_by="b@example.com")
    assert info.value.code == "maturity_bulk_run_in_progress"

    bulk.execute_run(first["id"], scope, session_factory=lambda: _same_session(db_session),
                     evaluator_factory=lambda: _FakeEvaluator({}))
    assert bulk.start_run(scope, started_by="b@example.com")["state"] == "running"


def test_the_worker_count_bounds_the_evaluations_in_flight(db_session, monkeypatch):
    _level(db_session, 1, "Prerequisite")
    for i in range(12):
        _asset(db_session, f"bulk.sales.t{i}")
    lock = threading.Lock()
    in_flight = {"now": 0, "peak": 0}

    def slow_evaluation(asset_id, **kwargs):
        with lock:
            in_flight["now"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
        time.sleep(0.02)
        with lock:
            in_flight["now"] -= 1
        return {"kind": "evaluated", "changed": False}

    monkeypatch.setattr(bulk, "_evaluate_one", slow_evaluation)

    final = _run(db_session, _bulk_scope(), _FakeEvaluator({}), max_workers=3, batch_size=5)

    assert final["processed"] == 12
    assert 2 <= in_flight["peak"] <= 3


def test_the_summary_is_stored_and_read_back_after_a_restart(db_session):
    _level(db_session, 1, "Prerequisite")
    _asset(db_session, "bulk.sales.a")
    final = _run(db_session, _bulk_scope(), _FakeEvaluator({}))

    bulk._current = None  # a new process: nothing in memory
    stored = bulk.get_latest_run(session_factory=lambda: _same_session(db_session))

    assert stored["id"] == final["id"]
    assert stored["state"] == "completed"
    assert db_session.get(AppSettingDb, bulk.LAST_RUN_SETTING_KEY) is not None


def test_tuning_is_clamped_to_the_allowed_range():
    run = bulk.start_run(_bulk_scope(), max_workers=50, batch_size=0)

    assert run["max_workers"] == bulk.MAX_WORKERS_LIMIT
    assert run["batch_size"] == 1


def test_a_failure_of_the_run_itself_stops_it_with_a_code(db_session):
    _level(db_session, 1, "Prerequisite")
    _asset(db_session, "bulk.sales.a")
    scope = _bulk_scope()
    snapshot = bulk.start_run(scope, started_by="admin@example.com")

    def broken_session():
        raise RuntimeError("connection string leaked")

    bulk.execute_run(snapshot["id"], scope, session_factory=broken_session,
                     evaluator_factory=lambda: _FakeEvaluator({}))
    final = bulk.get_latest_run(session_factory=lambda: _same_session(db_session))

    assert final["state"] == "failed"
    assert final["finished_at"] is not None
    assert final["errors"] == [{"asset_id": "", "code": "maturity_bulk_run_failed", "params": {}}]
    assert "connection string leaked" not in json.dumps(final)


def test_a_run_reads_the_uc_tables_with_the_given_identity(db_session):
    # An admin-started run passes the admin's identity; the app's client is not used
    from unittest.mock import MagicMock, patch

    from databricks.sdk.service.catalog import ColumnInfo, TableInfo
    from src.common.run_identity import RunIdentity
    from src.db_models.compliance import CompliancePolicyDb
    from src.repositories.maturity_repository import maturity_repo

    _level(db_session, 1, "Has columns")
    level = db_session.query(MaturityLevelDb).filter_by(entity_type="Asset").one()
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name="Columns",
                                rule="ASSERT obj.column_count > 0", is_active=True)
    db_session.add(policy)
    db_session.flush()
    maturity_repo.add_gate(db_session, maturity_level_id=level.id,
                           compliance_policy_id=policy.id)
    db_session.flush()
    asset_id = _asset(db_session, "bulkid.sales.orders")
    user_ws = MagicMock()
    user_ws.tables.get.return_value = TableInfo(
        full_name="bulkid.sales.orders",
        columns=[ColumnInfo(name="id", comment="Id", type_text="bigint")],
    )
    identity = RunIdentity(lambda: user_ws, on_behalf_of_user=True)
    scope = _bulk_scope(catalog="bulkid")

    with patch("src.common.workspace_client.get_workspace_client",
               side_effect=AssertionError("the app's client must not be used")):
        snapshot = bulk.start_run(scope, started_by="admin@example.com")
        bulk.execute_run(snapshot["id"], scope, evaluated_by="admin@example.com",
                         session_factory=lambda: _same_session(db_session),
                         run_identity=identity)

    user_ws.tables.get.assert_called_once_with(full_name="bulkid.sales.orders")
    stored = maturity_repo.list_snapshots(db_session, entity_type="Asset",
                                          entity_id=asset_id, limit=1)
    assert [s.achieved_level_order for s in stored] == [1]


def test_an_evaluation_that_stored_nothing_is_neither_evaluated_nor_changed(db_session):
    _level(db_session, 1, "Prerequisite")
    _level(db_session, 2, "1 star")
    unreadable = _asset(db_session, "bulkns.sales.unreadable")
    readable = _asset(db_session, "bulkns.sales.readable")
    _snapshot(db_session, unreadable, 2, minutes_from_now=-30)
    # The unreadable table reports its certain level 1, below the stored 2, and stores nothing
    evaluator = _FakeEvaluator({unreadable: _NotStored(1), readable: 1})

    final = _run(db_session, _bulk_scope(catalog="bulkns"), evaluator)

    assert (final["total"], final["processed"]) == (2, 2)
    assert final["evaluated"] == 1 and final["changed"] == 1
    assert final["skipped"] == {"maturity_bulk_skipped_not_stored": 1}
    assert final["error_count"] == 0


def test_a_run_that_outlasts_the_token_stops_with_an_error(db_session):
    """RunIdentity keeps one client for the run: once the token expires, Unity Catalog
    answers 401 (Unauthenticated) for every later table. The run stops there and fails
    with a coded error instead of finishing green with the rest skipped (#1414 review)."""
    from unittest.mock import MagicMock

    from databricks.sdk.errors import Unauthenticated
    from databricks.sdk.service.catalog import ColumnInfo, TableInfo
    from src.common.run_identity import RunIdentity
    from src.db_models.compliance import CompliancePolicyDb
    from src.repositories.maturity_repository import maturity_repo

    _level(db_session, 1, "Has columns")
    level = db_session.query(MaturityLevelDb).filter_by(entity_type="Asset").one()
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name="Columns",
                                rule="ASSERT obj.column_count > 0", is_active=True)
    db_session.add(policy)
    db_session.flush()
    maturity_repo.add_gate(db_session, maturity_level_id=level.id,
                           compliance_policy_id=policy.id)
    db_session.flush()
    fqns = ("bulktok.sales.a", "bulktok.sales.b", "bulktok.sales.c")
    ids = {fqn: _asset(db_session, fqn) for fqn in fqns}
    for asset_id in ids.values():
        _snapshot(db_session, asset_id, 1, minutes_from_now=-30)
    calls = []
    table = TableInfo(full_name="x", columns=[ColumnInfo(name="id", comment="Id",
                                                         type_text="bigint")])

    def get(full_name):
        calls.append(full_name)
        if len(calls) > 1:
            raise Unauthenticated("Token expired")
        return table

    user_ws = MagicMock()
    user_ws.tables.get.side_effect = get
    built = []
    identity = RunIdentity(lambda: built.append(1) or user_ws, on_behalf_of_user=True)
    scope = _bulk_scope(catalog="bulktok")

    snapshot = bulk.start_run(scope, started_by="admin@example.com", max_workers=1,
                              batch_size=1)
    bulk.execute_run(snapshot["id"], scope, evaluated_by="admin@example.com",
                     session_factory=lambda: _same_session(db_session),
                     run_identity=identity)
    final = bulk.get_latest_run(session_factory=lambda: _same_session(db_session))

    assert built == [1]  # the client is built once and not re-resolved
    assert len(calls) == 2  # the table after the refused one is not read
    assert final["state"] == "failed"
    assert final["evaluated"] == 1 and final["skipped"] == {}
    assert final["errors"] == [{"asset_id": ids[calls[1]],
                                "code": "maturity_bulk_authentication_failed", "params": {}}]
    # The table read before the expiry got a new snapshot; the refused one did not
    counts = {
        fqn: len(maturity_repo.list_snapshots(db_session, entity_type="Asset",
                                              entity_id=ids[fqn]))
        for fqn in fqns
    }
    assert counts[calls[0]] == 2 and counts[calls[1]] == 1
    assert sorted(counts.values()) == [1, 1, 2]


def test_a_refused_token_on_one_asset_read_stays_an_unreadable_table():
    """Outside a bulk run (an asset GET or write) a refused token reads as unreadable."""
    from src.controller.maturity_evaluator import _uc_notice

    notice = _uc_notice({"uc_table_status": "unauthenticated", "uc_table_name": "a.b.c"})
    assert notice.code == "maturity_uc_table_unreadable"
