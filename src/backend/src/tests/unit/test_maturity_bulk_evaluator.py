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
    def __init__(self, order):
        self.achieved_level_order = order


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
