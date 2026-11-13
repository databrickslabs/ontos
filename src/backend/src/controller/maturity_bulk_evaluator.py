"""Bulk maturity evaluation of table and view assets.

A run selects the table and view assets of a scope (catalog, schema and asset types),
evaluates each one with the per-asset evaluator (``MaturityEvaluator``, persisted) in
batches, with a bounded number of worker threads, and keeps progress and a summary.

- Idempotent: an asset whose latest snapshot is at or after the run's start was already
  evaluated since the run started (a retry, a double request), and is skipped with a
  counted reason. A level change is logged and fires ON_MATURITY_CHANGE as for any
  evaluation.
- Errors are counted and coded (``maturity_bulk_evaluation_failed``); the exception text
  goes to the server log only.
- The summary of the last run is stored in ``app_settings`` so it survives a restart.
  Progress of a running run lives in this process.

Scheduling is not part of this module: the run is started from the API (see
``routes/maturity_routes.py``).
"""
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.database import get_db_session
from src.common.logging import get_logger
from src.controller.entity_dict_builder import (
    MATURITY_ASSET_TYPES,
    UnsupportedMaturityAssetTypeError,
)
from src.controller.maturity_evaluator import MaturityEvaluator
from src.db_models.app_settings import AppSettingDb
from src.db_models.assets import AssetDb, AssetTypeDb
from src.repositories.maturity_repository import maturity_repo

logger = get_logger(__name__)

LAST_RUN_SETTING_KEY = "maturity_bulk_last_run"

DEFAULT_MAX_WORKERS = 4
MAX_WORKERS_LIMIT = 8
DEFAULT_BATCH_SIZE = 100
MAX_BATCH_SIZE = 500
MAX_RECORDED_ERRORS = 100

SKIP_EVALUATED_IN_RUN = "maturity_bulk_skipped_evaluated_in_run"
SKIP_NOT_FOUND = "maturity_bulk_skipped_not_found"
SKIP_NO_LEVELS = "maturity_bulk_skipped_no_levels"
SKIP_ASSET_TYPE = "maturity_bulk_skipped_asset_type"
ERROR_EVALUATION_FAILED = "maturity_bulk_evaluation_failed"
ERROR_RUN_FAILED = "maturity_bulk_run_failed"

SessionFactory = Callable[[], Any]


class MaturityBulkScopeError(CodedValueError):
    """The scope of a bulk evaluation is not valid."""
    code = "maturity_bulk_scope_invalid"


class MaturityBulkRunInProgressError(CodedValueError):
    """A bulk evaluation is already running in this process."""
    code = "maturity_bulk_run_in_progress"


@dataclass(frozen=True)
class BulkScope:
    catalog: Optional[str] = None
    schema_name: Optional[str] = None
    asset_types: Tuple[str, ...] = tuple(MATURITY_ASSET_TYPES)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "catalog": self.catalog,
            "schema": self.schema_name,
            "asset_types": list(self.asset_types),
        }


def normalize_scope(
    catalog: Optional[str] = None,
    schema_name: Optional[str] = None,
    asset_types: Optional[Sequence[str]] = None,
) -> BulkScope:
    """Validate the request scope; an empty catalog means every catalog."""
    cat = (catalog or "").strip() or None
    sch = (schema_name or "").strip() or None
    if sch and not cat:
        raise MaturityBulkScopeError("A schema scope needs a catalog.")
    for part in (cat, sch):
        if part and ("." in part or "`" in part):
            raise MaturityBulkScopeError("A catalog or schema name has no dots or backticks.")
    canonical = {name.lower(): name for name in MATURITY_ASSET_TYPES}
    if not asset_types:
        types = tuple(MATURITY_ASSET_TYPES)
    else:
        if any(str(t).strip().lower() not in canonical for t in asset_types):
            raise MaturityBulkScopeError("Maturity levels apply to table and view assets.")
        types = tuple(dict.fromkeys(canonical[str(t).strip().lower()] for t in asset_types))
    return BulkScope(catalog=cat, schema_name=sch, asset_types=types)


def select_asset_ids(db: Session, scope: BulkScope) -> List[str]:
    """Ids of the table and view assets in the scope, in a stable order."""
    query = (
        db.query(AssetDb.id)
        .join(AssetTypeDb, AssetDb.asset_type_id == AssetTypeDb.id)
        .filter(AssetTypeDb.name.in_(scope.asset_types))
    )
    if scope.catalog:
        prefix = f"{scope.catalog}."
        if scope.schema_name:
            prefix += f"{scope.schema_name}."
        # Unity Catalog names are case-insensitive; a literal prefix match (no LIKE)
        query = query.filter(
            func.lower(AssetDb.location).startswith(prefix.lower(), autoescape=True)
        )
    return [str(row.id) for row in query.order_by(AssetDb.id).all()]


# --- Run registry ---------------------------------------------------------------

_lock = threading.Lock()
_current: Optional[Dict[str, Any]] = None  # the running run, or the last one in this process


def _bounded(value: Optional[int], default: int, high: int) -> int:
    if value is None:
        return default
    return max(1, min(int(value), high))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialise(run: Dict[str, Any]) -> Dict[str, Any]:
    """A copy of a run that can be stored as JSON and returned by the API."""
    def default(value: Any) -> Any:
        return value.isoformat() if isinstance(value, datetime) else str(value)
    return json.loads(json.dumps(run, default=default))


def start_run(
    scope: BulkScope,
    *,
    started_by: Optional[str] = None,
    max_workers: Optional[int] = None,
    batch_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Register a new run and return its first snapshot; one run at a time."""
    global _current
    with _lock:
        if _current is not None and _current["state"] == "running":
            raise MaturityBulkRunInProgressError(
                "A bulk maturity evaluation is already running.",
            )
        _current = {
            "id": str(uuid.uuid4()),
            "state": "running",
            "scope": scope.as_dict(),
            "started_by": started_by,
            "started_at": _now(),
            "finished_at": None,
            "max_workers": _bounded(max_workers, DEFAULT_MAX_WORKERS, MAX_WORKERS_LIMIT),
            "batch_size": _bounded(batch_size, DEFAULT_BATCH_SIZE, MAX_BATCH_SIZE),
            "total": 0,
            "processed": 0,
            "evaluated": 0,
            "changed": 0,
            "skipped": {},
            "error_count": 0,
            "errors": [],
        }
        return _serialise(_current)


def get_latest_run(session_factory: SessionFactory = get_db_session) -> Optional[Dict[str, Any]]:
    """The running run, else the last one of this process, else the last stored one."""
    with _lock:
        if _current is not None:
            return _serialise(_current)
    try:
        with session_factory() as db:
            setting = db.get(AppSettingDb, LAST_RUN_SETTING_KEY)
            raw = setting.value if setting else None
    except Exception:
        logger.warning("Could not read the last bulk maturity run", exc_info=True)
        return None
    return json.loads(raw) if raw else None


def _update(run_id: str, **fields: Any) -> None:
    with _lock:
        if _current is not None and _current["id"] == run_id:
            _current.update(fields)


def _record(run_id: str, outcome: Dict[str, Any]) -> None:
    with _lock:
        if _current is None or _current["id"] != run_id:
            return
        _current["processed"] += 1
        kind = outcome["kind"]
        if kind == "evaluated":
            _current["evaluated"] += 1
            if outcome.get("changed"):
                _current["changed"] += 1
        elif kind == "skipped":
            code = outcome["code"]
            _current["skipped"][code] = _current["skipped"].get(code, 0) + 1
        else:
            _current["error_count"] += 1
            if len(_current["errors"]) < MAX_RECORDED_ERRORS:
                _current["errors"].append({
                    "asset_id": outcome["asset_id"], "code": outcome["code"], "params": {},
                })


def _finish(run_id: str, state: str, session_factory: SessionFactory) -> None:
    with _lock:
        if _current is None or _current["id"] != run_id:
            return
        _current["state"] = state
        _current["finished_at"] = _now()
        snapshot = _serialise(_current)
    try:
        with session_factory() as db:
            setting = db.get(AppSettingDb, LAST_RUN_SETTING_KEY)
            if setting is None:
                setting = AppSettingDb(key=LAST_RUN_SETTING_KEY)
                db.add(setting)
            setting.value = json.dumps(snapshot)
            db.flush()
    except Exception:
        # The run is over either way; the summary stays in memory until the next restart
        logger.warning("Could not store the bulk maturity run summary", exc_info=True)


# --- Evaluation -------------------------------------------------------------------

def _batches(items: List[str], size: int) -> Iterator[List[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _evaluate_one(
    asset_id: str,
    *,
    started_at: datetime,
    evaluated_by: Optional[str],
    session_factory: SessionFactory,
    evaluator_factory: Callable[[], MaturityEvaluator],
) -> Dict[str, Any]:
    """Evaluate one asset in its own session. Never raises."""
    try:
        with session_factory() as db:
            latest = maturity_repo.list_snapshots(db, entity_type="Asset",
                                                  entity_id=asset_id, limit=1)
            if latest and _aware(latest[0].evaluated_at) >= started_at:
                return {"kind": "skipped", "code": SKIP_EVALUATED_IN_RUN}
            previous = latest[0].achieved_level_order if latest else None
            report = evaluator_factory().evaluate(
                db, entity_type="Asset", entity_id=asset_id,
                persist=True, evaluated_by=evaluated_by,
            )
            if report is None:
                return {"kind": "skipped", "code": SKIP_NOT_FOUND}
            return {
                "kind": "evaluated",
                "changed": report.achieved_level_order != previous,
            }
    except UnsupportedMaturityAssetTypeError:
        return {"kind": "skipped", "code": SKIP_ASSET_TYPE}
    except Exception:
        logger.warning("Bulk maturity evaluation failed for asset %s", asset_id, exc_info=True)
        return {"kind": "error", "code": ERROR_EVALUATION_FAILED, "asset_id": asset_id}


def execute_run(
    run_id: str,
    scope: BulkScope,
    *,
    evaluated_by: Optional[str] = None,
    session_factory: SessionFactory = get_db_session,
    evaluator_factory: Optional[Callable[[], MaturityEvaluator]] = None,
) -> None:
    """Evaluate every asset of the scope for a run registered with start_run."""
    make_evaluator = evaluator_factory or MaturityEvaluator
    with _lock:
        if _current is None or _current["id"] != run_id:
            return
        started_at = _current["started_at"]
        max_workers = _current["max_workers"]
        batch_size = _current["batch_size"]
    try:
        with session_factory() as db:
            asset_ids = select_asset_ids(db, scope)
            has_levels = bool(maturity_repo.get_all_ordered(db, entity_type="Asset"))
        _update(run_id, total=len(asset_ids))
        if not has_levels:
            # Nothing to evaluate against: every asset is counted, none is evaluated
            for _ in asset_ids:
                _record(run_id, {"kind": "skipped", "code": SKIP_NO_LEVELS})
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for batch in _batches(asset_ids, batch_size):
                    futures = [
                        pool.submit(
                            _evaluate_one, asset_id, started_at=started_at,
                            evaluated_by=evaluated_by, session_factory=session_factory,
                            evaluator_factory=make_evaluator,
                        )
                        for asset_id in batch
                    ]
                    for future in as_completed(futures):
                        _record(run_id, future.result())
        _finish(run_id, "completed", session_factory)
    except Exception:
        logger.error("Bulk maturity evaluation %s failed", run_id, exc_info=True)
        with _lock:
            if _current is not None and _current["id"] == run_id:
                _current["error_count"] += 1
                _current["errors"].append({"asset_id": "", "code": ERROR_RUN_FAILED, "params": {}})
        _finish(run_id, "failed", session_factory)
