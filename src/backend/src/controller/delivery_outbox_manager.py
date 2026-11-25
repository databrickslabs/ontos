"""The delivery outbox (#1688): deliver a change once it is committed, and retry it.

A change to deliver (Git, Unity Catalog, a manual task) gets one ``delivery_outbox``
row per active delivery mode, written in the change's own transaction: a change
that rolls back leaves no row, a committed one can't be lost. After the commit
the rows are tried once at once (``deliver_after_commit``); a row whose attempt
failed stays ``pending`` and the workflow scheduler's thread tries it again
(``DeliveryOutboxWorker``), with a growing delay, until ``MAX_ATTEMPTS``; then it
is ``failed`` until someone delivers the entity again (``redeliver``).

An attempt claims its row with ``SELECT ... FOR UPDATE SKIP LOCKED`` (Postgres) in
a session of its own and holds the lock until it records the outcome, so two app
instances, or the worker and the attempt after a commit, never deliver the same
row together. It reads the entity in that session: never an object of the
request's session, expired or detached once that one committed.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from src.common.after_commit import run_after_commit
from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.db_models.delivery_outbox import DeliveryOutboxDb
from src.models.delivery_outbox import DeliveryOutboxList, DeliveryOutboxRow
from src.models.import_results import ImportDeliveryResult
from src.repositories.delivery_outbox_repository import (
    DELIVERED, FAILED, OPEN_STATUSES, PENDING, delivery_outbox_repo,
)
from src.repositories.scheduler_claims_repository import scheduler_claims_repo

logger = get_logger(__name__)

# Attempts of a row, the one after the commit included; then it stays ``failed``.
MAX_ATTEMPTS = 5
# The delay after the n-th failed attempt: RETRY_BASE * RETRY_FACTOR ** (n - 1), capped.
RETRY_BASE = timedelta(minutes=1)
RETRY_FACTOR = 4
RETRY_CAP = timedelta(hours=6)
# A new row is left to the attempt after its commit this long before the worker takes it.
FIRST_ATTEMPT_GRACE = timedelta(minutes=1)
# Delivered rows are deleted after this long (failed ones are kept), once a day.
RETENTION = timedelta(days=30)
PRUNE_TASK_KEY = 'delivery-outbox-prune'
# With requests coming in, the worker also looks for due rows once per slot this long:
# rows another instance queued, or left pending by a process that stopped.
SWEEP_INTERVAL = timedelta(minutes=5)
# Rows delivered per pass; the next pass follows at once when there were more.
MAX_ROWS_PER_PASS = 50
# A due row another instance holds is looked at again this much later.
LOCKED_RECHECK = timedelta(seconds=30)
# After a failed pass (e.g. the database is unreachable): 1 minute, doubling up to 1 hour.
ERROR_RETRY = timedelta(minutes=1)
ERROR_RETRY_CAP = timedelta(hours=1)

# Codes of a delivered row with nothing done, and of a not yet tried one
NOT_APPLICABLE = 'delivery_not_applicable'
MODE_INACTIVE = 'delivery_mode_inactive'
# The delivery went through but its outcome couldn't be saved: delivered, never retried
OUTCOME_UNRECORDED = 'delivery_outcome_unrecorded'
PENDING_CODE = 'delivery_pending'
IN_PROGRESS_CODE = 'delivery_in_progress'


class DeliveryEntityTypeUnsupportedError(CodedValueError):
    code = 'delivery_entity_type_unsupported'


class DeliveryEntityNotFoundError(CodedValueError):
    code = 'delivery_entity_not_found'


class DeliveryNoActiveModeError(CodedValueError):
    code = 'delivery_no_active_mode'


@dataclass(frozen=True)
class _EntityKind:
    """An entity type the outbox delivers: its ORM class, and the change of a re-delivery."""

    model: Callable[[], type]
    redeliver_change: str


def _data_product_model() -> type:
    from src.db_models.data_products import DataProductDb
    return DataProductDb


# The import path (#1671) and the re-delivery use the outbox; the other delivery
# callers move to it once #1674 (Indirect delivery in the request) is merged.
ENTITY_KINDS: Dict[str, _EntityKind] = {
    'DataProduct': _EntityKind(_data_product_model, 'product_update'),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """An aware UTC datetime; SQLite returns naive values, stored as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def retry_delay(attempts: int) -> timedelta:
    """How long after its ``attempts``-th failed attempt a row is tried again."""
    delay = RETRY_BASE * (RETRY_FACTOR ** max(0, attempts - 1))
    return min(delay, RETRY_CAP)


def _mode_value(mode: Any) -> str:
    return getattr(mode, 'value', mode)


def _delivery_service():
    """The app's delivery service, or None before it is initialized (delivery is off)."""
    from src.controller.delivery_service import get_delivery_service
    try:
        return get_delivery_service()
    except RuntimeError:
        return None


def _active_modes(service) -> List[str]:
    if service is None:
        return []
    return [_mode_value(mode) for mode in service.get_active_modes() or []]


def notify_scheduler(when: Optional[datetime]) -> None:
    """A row of this instance is due at ``when``: the scheduler's worker takes it then."""
    if when is None:
        return
    from src.controller.workflow_scheduler import notify_delivery_queued
    notify_delivery_queued(when)


# --- outcome of rows ---------------------------------------------------------------

def _failed_now(row: Any) -> bool:
    """A failed row, or a pending one whose last attempt failed (it is retried)."""
    return row.status == FAILED or (row.status == PENDING and bool(row.attempts) and bool(row.code))


def outcome_of(rows: Sequence[Any]) -> Optional[ImportDeliveryResult]:
    """One outcome for the rows of a change: ``failed`` (the first failed mode's coded
    reason) when a mode's last attempt failed, ``pending`` when one wasn't tried,
    ``skipped`` when no mode applied, else ``delivered``; None without rows."""
    if not rows:
        return None
    failed = [row for row in rows if _failed_now(row)]
    if failed:
        first = failed[0]
        params = dict(first.params or {})
        params.setdefault('mode', first.mode)
        return ImportDeliveryResult(status='failed', code=first.code or 'delivery_failed',
                                    params=params)
    pending = [row for row in rows if row.status == PENDING]
    if pending:
        return ImportDeliveryResult(status='pending', code=PENDING_CODE,
                                    params={'mode': pending[0].mode})
    if all(row.code in (NOT_APPLICABLE, MODE_INACTIVE) for row in rows):
        return ImportDeliveryResult(status='skipped', code=NOT_APPLICABLE)
    return ImportDeliveryResult(status='delivered', params={'modes': [row.mode for row in rows]})


def row_model(row: DeliveryOutboxDb, entity_name: Optional[str] = None) -> DeliveryOutboxRow:
    return DeliveryOutboxRow(
        id=row.id, entity_type=row.entity_type, entity_id=row.entity_id,
        entity_name=entity_name, change_type=row.change_type, mode=row.mode,
        status=row.status, code=row.code, params=row.params, attempts=row.attempts or 0,
        max_attempts=MAX_ATTEMPTS, next_attempt_at=_utc(row.next_attempt_at),
        last_attempt_at=_utc(row.last_attempt_at), delivered_at=_utc(row.delivered_at),
        queued_by=row.queued_by, created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


# --- queue and deliver ---------------------------------------------------------------

def queue(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    change_type: Any,
    user: Optional[str],
    now: Optional[datetime] = None,
    modes: Optional[Sequence[str]] = None,
) -> List[str]:
    """Add a pending row per delivery mode (default: the active ones) to ``db``'s
    transaction (not committed); their ids, none when no mode is active."""
    if modes is None:
        modes = _active_modes(_delivery_service())
    now = now or _now()
    return [
        delivery_outbox_repo.add(
            db, entity_type=entity_type, entity_id=str(entity_id),
            change_type=_mode_value(change_type), mode=mode, queued_by=user,
            next_attempt_at=now + FIRST_ATTEMPT_GRACE,
        ).id
        for mode in modes
    ]


def _payload(row: DeliveryOutboxDb, entity: Any):
    from src.controller.delivery_service import DeliveryChangeType, DeliveryPayload
    return DeliveryPayload(
        change_type=DeliveryChangeType(row.change_type), entity_type=row.entity_type,
        entity_id=row.entity_id, data={'entity': entity}, user=row.queued_by,
    )


def _deliver_claimed(db: Session, row: DeliveryOutboxDb, now: datetime) -> None:
    """Deliver a row this session holds and set its outcome (the caller commits)."""
    from src.controller.delivery_service import DeliveryMode

    service = _delivery_service()
    if service is None:
        # Not initialized (startup): not an attempt, try it again later
        row.next_attempt_at = now + RETRY_BASE
        return
    if row.mode not in _active_modes(service):
        delivery_outbox_repo.record(row, status=DELIVERED, now=now, code=MODE_INACTIVE,
                                    counted=False)
        return
    kind = ENTITY_KINDS.get(row.entity_type)
    if kind is None:
        delivery_outbox_repo.record(row, status=FAILED, now=now,
                                    code='delivery_entity_type_unsupported',
                                    params={'mode': row.mode})
        return
    entity = db.get(kind.model(), row.entity_id)
    if entity is None:
        logger.warning("Not delivering %s %s: it no longer exists", row.entity_type,
                       row.entity_id)
        delivery_outbox_repo.record(row, status=FAILED, now=now,
                                    code='delivery_entity_not_found', params={'mode': row.mode})
        return
    try:
        results = service.deliver(_payload(row, entity), modes=[DeliveryMode(row.mode)])
        result = results.results[0] if results.results else None
    except Exception:
        logger.warning("Delivery of %s %s via %s raised", row.entity_type, row.entity_id,
                       row.mode, exc_info=True)
        result = None
    if result is not None and result.success:
        # From here the delivery is done: if saving the outcome breaks, the row is not
        # a failed attempt (see ``_record_unrecorded``)
        row.delivery_done = True
        skipped = bool((result.details or {}).get('skipped'))
        delivery_outbox_repo.record(row, status=DELIVERED, now=now,
                                    code=NOT_APPLICABLE if skipped else None)
        return
    details = (result.details or {}) if result is not None else {}
    code = details.get('error_code') or 'delivery_failed'
    params = {**(details.get('error_params') or {}), 'mode': row.mode}
    attempts = (row.attempts or 0) + 1
    if attempts >= MAX_ATTEMPTS:
        status, next_attempt = FAILED, None
    else:
        status, next_attempt = PENDING, now + retry_delay(attempts)
    logger.warning("%s %s not delivered via %s (attempt %d of %d): %s", row.entity_type,
                   row.entity_id, row.mode, attempts, MAX_ATTEMPTS, code)
    delivery_outbox_repo.record(row, status=status, now=now, code=code, params=params,
                                next_attempt_at=next_attempt)


def _record_unrecorded(
    session_factory: Callable[[], Session], row_id: str, now: datetime,
) -> None:
    """Record, in a session and transaction of its own, a row whose delivery went
    through but whose outcome couldn't be saved: delivered (never retried), with a
    code of its own, not a failed attempt."""
    db = session_factory()
    try:
        row = delivery_outbox_repo.claim(db, row_id)
        if row is not None:
            delivery_outbox_repo.record(row, status=DELIVERED, now=now, code=OUTCOME_UNRECORDED)
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def attempt(
    session_factory: Callable[[], Session], row_id: str, now: Optional[datetime] = None,
) -> Optional[DeliveryOutboxRow]:
    """Deliver the pending row ``row_id`` now, in a session of its own; the row
    afterwards (as it is when another session holds it or it isn't pending), or
    None when it doesn't exist."""
    db = session_factory()
    row = None
    try:
        row = delivery_outbox_repo.claim(db, row_id)
        if row is None:
            current = delivery_outbox_repo.get(db, row_id)
            return row_model(current) if current is not None else None
        _deliver_claimed(db, row, _utc(now) or _now())
        db.commit()
        return row_model(row)
    except Exception:
        logger.error("Delivery attempt of outbox row %s failed", row_id, exc_info=True)
        db.rollback()
        if getattr(row, 'delivery_done', False):
            try:
                _record_unrecorded(session_factory, row_id, _utc(now) or _now())
            except Exception:
                logger.error("Outcome of outbox row %s not recorded", row_id, exc_info=True)
        current = delivery_outbox_repo.get(db, row_id)
        return row_model(current) if current is not None else None
    finally:
        db.close()


def attempt_all(
    session_factory: Callable[[], Session], row_ids: Iterable[str],
    now: Optional[datetime] = None,
) -> List[DeliveryOutboxRow]:
    """``attempt`` each row; the pending ones are left to the scheduler's worker."""
    rows = [row for row in (attempt(session_factory, row_id, now) for row_id in row_ids)
            if row is not None]
    due = [row.next_attempt_at for row in rows if row.status == PENDING and row.next_attempt_at]
    if due:
        notify_scheduler(min(due))
    return rows


def deliver_after_commit(
    db: Session,
    row_ids: List[str],
    on_outcome: Optional[Callable[[ImportDeliveryResult], None]] = None,
    *,
    entity_label: str = '',
) -> None:
    """Try ``row_ids`` once ``db``'s outermost transaction has committed (nothing when
    it rolls back), each in a session of its own; ``on_outcome`` gets their outcome
    inside the ``commit()`` call."""
    if not row_ids:
        return
    bind = db.get_bind()

    def attempt_rows() -> None:
        rows = attempt_all(lambda: Session(bind=bind, expire_on_commit=False), row_ids)
        outcome = outcome_of(rows)
        if outcome is not None and outcome.status == 'failed':
            logger.warning("%s was committed but not delivered: %s %s", entity_label,
                           outcome.code, outcome.params or {})
        if outcome is not None and on_outcome is not None:
            on_outcome(outcome)

    run_after_commit(db, attempt_rows)


# --- Settings > Delivery Modes ---------------------------------------------------------

@dataclass(frozen=True)
class Redelivery:
    """What ``redeliver`` queued: the rows to try, and the open rows another session
    holds (an attempt under way), which it left alone."""

    row_ids: List[str]
    in_progress: List[str]


class DeliveryOutboxManager:
    """The outbox rows an admin sees on Settings > Delivery Modes, and re-delivery."""

    def list_rows(
        self, db: Session, statuses: Iterable[str] = OPEN_STATUSES, limit: int = 100,
    ) -> DeliveryOutboxList:
        statuses = [s for s in statuses if s in (PENDING, DELIVERED, FAILED)] or OPEN_STATUSES
        rows = delivery_outbox_repo.list(db, statuses, limit=limit)
        names = self._entity_names(db, rows)
        return DeliveryOutboxList(
            rows=[row_model(row, names.get((row.entity_type, row.entity_id))) for row in rows],
            counts=delivery_outbox_repo.count(db, statuses),
        )

    @staticmethod
    def _entity_names(db: Session, rows: Sequence[DeliveryOutboxDb]) -> Dict[tuple, str]:
        names: Dict[tuple, str] = {}
        for entity_type, kind in ENTITY_KINDS.items():
            ids = {row.entity_id for row in rows if row.entity_type == entity_type}
            if not ids:
                continue
            model = kind.model()
            for entity_id, name in db.query(model.id, model.name).filter(model.id.in_(ids)):
                names[(entity_type, entity_id)] = name
        return names

    def redeliver(
        self, db: Session, entity_type: str, entity_id: str, user: Optional[str],
        now: Optional[datetime] = None,
    ) -> Redelivery:
        """Queue the entity again and commit; the ids of the rows to try.

        Its open rows (pending or failed) of an active mode start over; those of a mode
        turned off since are closed (``delivery_mode_inactive``); an active mode without
        an open row gets a new one for the entity's current state. A row another session
        holds (an attempt under way) is left alone and reported in ``in_progress``.
        """
        kind = ENTITY_KINDS.get(entity_type)
        if kind is None:
            raise DeliveryEntityTypeUnsupportedError(
                f"Entity type {entity_type} can't be delivered again", entityType=entity_type)
        if db.get(kind.model(), entity_id) is None:
            raise DeliveryEntityNotFoundError(
                f"{entity_type} {entity_id} not found", entityType=entity_type,
                entityId=entity_id)
        if not _active_modes(_delivery_service()):
            raise DeliveryNoActiveModeError("No delivery mode is active")
        now = _utc(now) or _now()
        active = _active_modes(_delivery_service())
        open_rows = delivery_outbox_repo.for_entity(db, entity_type, entity_id)
        rows = delivery_outbox_repo.for_entity(db, entity_type, entity_id, lock=True)
        locked = {row.id for row in rows}
        held = {row.id for row in open_rows} - locked
        ids = []
        for row in rows:
            if row.mode not in active:
                # Its mode was turned off since: nothing to try, close it
                delivery_outbox_repo.record(row, status=DELIVERED, now=now, code=MODE_INACTIVE,
                                            counted=False)
                continue
            row.status, row.attempts, row.code, row.params = PENDING, 0, None, None
            row.next_attempt_at, row.delivered_at = now + FIRST_ATTEMPT_GRACE, None
            row.queued_by, row.updated_at = user, now
            ids.append(row.id)
        # A mode turned on since has no row yet; one with a held row has its attempt
        covered = {row.mode for row in open_rows}
        ids += queue(
            db, entity_type=entity_type, entity_id=entity_id,
            change_type=kind.redeliver_change, user=user, now=now,
            modes=[mode for mode in active if mode not in covered],
        )
        db.commit()
        return Redelivery(ids, sorted(held))

    def rows_of(self, db: Session, row_ids: Iterable[str]) -> List[DeliveryOutboxDb]:
        return delivery_outbox_repo.by_ids(db, row_ids)


delivery_outbox_manager = DeliveryOutboxManager()


# --- the scheduler's worker -------------------------------------------------------------

class DeliveryOutboxWorker:
    """Delivers the due pending rows from the workflow scheduler's thread.

    Like the scheduler, it doesn't poll an idle database: a pass runs on the
    scheduler's first pass, when a request (the database is awake) notes that a
    new ``SWEEP_INTERVAL`` slot began, and at the time the next pending row it
    knows of is due (rows of this instance, or seen by its last pass). With no
    pending row, nothing wakes it up. Delivered rows older than ``RETENTION`` are
    deleted at most once a day across instances (claimed in ``scheduler_claims``).
    """

    def __init__(self, clock: Optional[Callable[[], datetime]] = None):
        self._clock = clock or _now
        self._lock = threading.Lock()
        self._first = True
        self._requested = False
        self._last_slot: Optional[datetime] = None
        self._next_due: Optional[datetime] = None
        self._failures = 0
        self._last_prune_day: Optional[datetime] = None

    @staticmethod
    def _slot_of(now: datetime) -> datetime:
        interval = SWEEP_INTERVAL.total_seconds()
        return datetime.fromtimestamp(now.timestamp() // interval * interval, tz=timezone.utc)

    def note_activity(self) -> bool:
        """A request uses the database; True when a pass is wanted (a new slot began)."""
        with self._lock:
            if self._requested or self._first:
                return False
            if self._last_slot is not None and self._slot_of(self._clock()) <= self._last_slot:
                return False
            self._requested = True
            return True

    def note_queued(self, when: datetime) -> None:
        """A row of this instance is due at ``when``."""
        when = _utc(when)
        with self._lock:
            if self._next_due is None or when < self._next_due:
                self._next_due = when

    def next_deadline(self) -> Optional[datetime]:
        return self._next_due

    def due(self, now: datetime) -> bool:
        next_due = self._next_due
        return self._first or self._requested or (next_due is not None and next_due <= now)

    def run(
        self, session_factory: Callable[[], Session], now: Optional[datetime] = None,
        claimed_by: str = '',
    ) -> int:
        """One pass: deliver the due rows, prune old delivered ones; the count delivered
        or tried. Failures are logged; the next pass is then retried later."""
        now = _utc(now) or self._clock()
        with self._lock:
            self._first = False
            self._requested = False
            self._last_slot = self._slot_of(now)
            self._next_due = None
        try:
            tried, more = self._sweep(session_factory, now)
            self._prune(session_factory, now, claimed_by)
            next_due = None if more else self._read_next_due(session_factory)
        except Exception as e:
            self._failures += 1
            retry = min(ERROR_RETRY * (2 ** (self._failures - 1)), ERROR_RETRY_CAP)
            logger.error(f"Delivery outbox pass failed ({type(e).__name__}); "
                         f"trying again in {int(retry.total_seconds())} s", exc_info=True)
            self.note_queued(now + retry)
            return 0
        self._failures = 0
        if more:
            self.note_queued(now)
        elif next_due is not None:
            # A due row still pending is held by another instance: look again later
            self.note_queued(next_due if next_due > now else now + LOCKED_RECHECK)
        return tried

    @staticmethod
    def _sweep(session_factory: Callable[[], Session], now: datetime) -> tuple:
        """Deliver due rows one at a time; ``(count, more_left)``."""
        tried = 0
        while tried < MAX_ROWS_PER_PASS:
            db = session_factory()
            row = row_id = None
            try:
                row = delivery_outbox_repo.claim_next_due(db, now)
                if row is None:
                    db.rollback()
                    return tried, False
                row_id = row.id
                _deliver_claimed(db, row, now)
                db.commit()
                tried += 1
            except Exception as e:
                db.rollback()
                if row_id is None:
                    raise
                # One bad row (the entity load, the outcome, the commit) must not stall
                # the rows behind it: count it as a failed attempt and go on. When the
                # delivery itself went through, it is recorded as delivered instead:
                # another attempt would repeat its external effect.
                logger.error("Delivery of outbox row %s broke before an outcome (%s)",
                             row_id, type(e).__name__, exc_info=True)
                if getattr(row, 'delivery_done', False):
                    _record_unrecorded(session_factory, row_id, now)
                else:
                    DeliveryOutboxWorker._fail_row(session_factory, row_id, now)
                tried += 1
            finally:
                db.close()
        return tried, True

    @staticmethod
    def _fail_row(session_factory: Callable[[], Session], row_id: str, now: datetime) -> None:
        """Record a failed attempt of a row in a session and transaction of its own."""
        db = session_factory()
        try:
            delivery_outbox_repo.fail_attempt(
                db, row_id, now=now, code='delivery_failed', max_attempts=MAX_ATTEMPTS,
                retry_after=retry_delay)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _read_next_due(session_factory: Callable[[], Session]) -> Optional[datetime]:
        db = session_factory()
        try:
            return _utc(delivery_outbox_repo.next_due_at(db))
        finally:
            db.close()

    def _prune(self, session_factory: Callable[[], Session], now: datetime,
               claimed_by: str) -> None:
        """Delete old delivered rows, once a day across instances."""
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if self._last_prune_day == day:
            return
        self._last_prune_day = day
        db = session_factory()
        try:
            if not scheduler_claims_repo.claim(
                db, task_key=PRUNE_TASK_KEY, slot=day, claimed_by=claimed_by,
                outcome={'status': 'claimed'},
            ):
                return  # another instance prunes today
            deleted = delivery_outbox_repo.prune_delivered(db, before=now - RETENTION)
            db.commit()
            scheduler_claims_repo.record_outcome(
                db, task_key=PRUNE_TASK_KEY, slot=day,
                outcome={'status': 'done', 'deleted': deleted},
            )
            if deleted:
                logger.info(f"Deleted {deleted} delivered outbox row(s) older than "
                            f"{RETENTION.days} days")
        except Exception as e:
            logger.warning(f"Could not delete old delivered outbox rows ({type(e).__name__})")
            db.rollback()
        finally:
            db.close()
