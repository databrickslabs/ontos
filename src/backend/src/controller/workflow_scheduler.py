"""Runs active workflows with a ``scheduled`` trigger (#941).

One thread per app process, like the job poller (``JobsManager.start_background_
polling``). Exactly-once across processes comes from ``scheduler_claims``: for
each due slot every instance inserts ``(workflow:<id>, slot)`` with ``ON CONFLICT
DO NOTHING`` and only the instance whose insert wrote the row runs the workflow.

Database access, so Lakebase can idle (no fixed polling):
- The schedules are kept in memory. The thread sleeps until the earliest known
  deadline (the next slot of any schedule; later periodic tasks add theirs) and
  reads the database only when a slot is due (the definitions are re-read first)
  or after a change. With nothing scheduled it sleeps until woken.
- The instance that saves a workflow (create, update, toggle, delete) re-reads at
  once (``notify_schedules_changed`` wakes its thread).
- Other instances learn of the change when the database is awake anyway: when one
  of their requests opens a transaction (``note_database_activity``, hooked into
  ``get_db``), the thread compares the workflows' ``(id, updated_at)`` with what it
  last read, at most once per ``change_check_seconds``, and re-reads on a
  difference. An instance without requests notices at its next due slot.
- ``idle_recheck_seconds`` > 0 adds that check on a timer as an opt-in fallback
  (each one can wake an idle Lakebase); 0, the default, means never.

A run gets a synthetic entity ``{type: schedule, id: <workflow id>, scheduled_for}``
and ``triggered_by = system:scheduler``; no user started it, so ``requester``
recipients resolve to nobody. The 5-minute minimum is a save-time rule; here a
slot less than 5 minutes after the last claimed one (a 29 February pair, a
schedule saved without the validator) is skipped, not the workflow.

Missed runs are coalesced: after downtime only the latest slot runs, if it is at
most one interval and at most 24 hours old, and its claim's
``outcome.coalesced_slots`` counts the slots it stands for. A slot before the
workflow's last change is not run, so creating or enabling a workflow doesn't run
a slot that passed before it.
"""
import json
import os
import socket
import threading
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.quartz_cron import (
    MIN_INTERVAL, QuartzCronError, count_runs, next_runs, previous_run, resolve_timezone,
    validate_in_app_cron,
)
from src.db_models.process_workflows import ProcessWorkflowDb
from src.models.process_workflows import TriggerContext, TriggerType
from src.repositories.scheduler_claims_repository import scheduler_claims_repo

logger = get_logger(__name__)

SCHEDULER_USER = 'system:scheduler'
SCHEDULE_ENTITY_TYPE = 'schedule'
TASK_KEY_PREFIX = 'workflow:'
# A missed slot older than this is not run (the grace is one interval, capped here).
MAX_GRACE = timedelta(hours=24)
# The coalesced count of a run after a long downtime counts at most this many slots.
COALESCE_COUNT_LIMIT = 10_000
# After a failed pass (e.g. the database is unreachable), try again this much later.
ERROR_RETRY_SECONDS = 60

_schedulers: 'weakref.WeakSet[WorkflowScheduler]' = weakref.WeakSet()
_schedulers_lock = threading.Lock()


def notify_schedules_changed() -> None:
    """A workflow changed: the schedulers of this process re-read the scheduled workflows."""
    with _schedulers_lock:
        schedulers = list(_schedulers)
    for scheduler in schedulers:
        scheduler.invalidate()


def note_database_activity() -> None:
    """A request is using the database: the schedulers may check for changes (rate-limited).

    Cheap and database-free; the check itself runs in each scheduler's thread.
    """
    with _schedulers_lock:
        schedulers = list(_schedulers)
    for scheduler in schedulers:
        scheduler.note_database_activity()


def task_key(workflow_id: str) -> str:
    return f'{TASK_KEY_PREFIX}{workflow_id}'


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """An aware UTC datetime; SQLite returns naive values, stored as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class _Schedule:
    workflow_id: str
    cron: str
    tz: Optional[str]
    changed_at: datetime
    handled_slot: Optional[datetime] = None


class WorkflowScheduler:
    """Fires ``scheduled`` workflows once per slot; see the module docstring."""

    def __init__(
        self,
        session_factory: Optional[Callable[[], Session]] = None,
        *,
        change_check_seconds: int = 60,
        idle_recheck_seconds: int = 0,
        clock: Optional[Callable[[], datetime]] = None,
        instance_id: Optional[str] = None,
    ):
        self._session_factory = session_factory
        # Shortest time between two request-triggered checks for changes.
        self._change_check = timedelta(seconds=max(0, int(change_check_seconds)))
        # 0 = never: then only requests and local changes make the scheduler look.
        self._idle_recheck = max(0, int(idle_recheck_seconds))
        # When the database was last read for the schedules (refresh or check).
        self._last_look: Optional[datetime] = None
        # ``(id, updated_at)`` of every workflow at the last refresh.
        self._fingerprint: Optional[frozenset] = None
        self._change_check_requested = False
        # Bumped by every invalidate(); a refresh that overlapped one keeps the flag
        # unknown, so a change committed after its query isn't lost.
        self._generation = 0
        self._short_gap_logged: set = set()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._claimed_by = instance_id or f'{socket.gethostname()}:{os.getpid()}'
        self._schedules: Dict[str, _Schedule] = {}
        # None = unknown (read the database on the next tick); False = no active
        # scheduled workflow (no database access); True = ``_schedules`` is current.
        self._has_scheduled: Optional[bool] = None
        self._run_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        with _schedulers_lock:
            _schedulers.add(self)

    # --- thread -----------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("Workflow scheduler already running")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name='WorkflowScheduler',
        )
        self._thread.start()
        from src.common.database import add_request_db_use_listener

        add_request_db_use_listener(note_database_activity)
        logger.info("Started the workflow scheduler")

    def stop(self) -> None:
        if not self._thread or not self._thread.is_alive():
            return
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=10)
        logger.info("Stopped the workflow scheduler")

    def invalidate(self) -> None:
        """Re-read the scheduled workflows now: wake the thread."""
        self._generation += 1
        self._has_scheduled = None
        self._wake.set()

    def note_database_activity(self) -> None:
        """The database is awake: check for changes made elsewhere, unless one was just made."""
        if self._change_check_requested or self._has_scheduled is None:
            return
        last = self._last_look
        if last is not None and self._clock() - last < self._change_check:
            return
        self._change_check_requested = True
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            # Cleared before the pass, so a wake-up during it isn't lost.
            self._wake.clear()
            try:
                delay = self.run_once()
            except Exception as e:
                logger.error(f"Workflow scheduler pass failed: {e}", exc_info=True)
                delay = ERROR_RETRY_SECONDS
            if self._stop.is_set():
                break
            self._wake.wait(timeout=delay)  # None: until woken

    # --- one tick ---------------------------------------------------------------

    def run_once(self, now: Optional[datetime] = None) -> Optional[float]:
        """Fire the due slots; return the seconds until the next deadline (None: none)."""
        with self._run_lock:
            now = _utc(now) if now else self._clock()
            check_requested, self._change_check_requested = self._change_check_requested, False
            if self._has_scheduled is None:
                self._refresh(now)
            elif check_requested or self._idle_recheck_due(now):
                self._check_for_changes(now)
            if self._has_scheduled and any(
                self._due_slot(s, now) for s in self._schedules.values()
            ):
                self._refresh(now)  # current definitions before running anything
                for schedule in list(self._schedules.values()):
                    slot = self._due_slot(schedule, now)
                    if slot is not None:
                        self._fire(schedule, slot)
            return self._sleep_seconds(now)

    def _session(self) -> Session:
        if self._session_factory is not None:
            return self._session_factory()
        from src.common.database import get_session_factory

        return get_session_factory()()

    def _idle_recheck_due(self, now: datetime) -> bool:
        return (
            self._idle_recheck > 0 and self._last_look is not None
            and (now - self._last_look).total_seconds() >= self._idle_recheck
        )

    @staticmethod
    def _fingerprint_of(rows) -> frozenset:
        return frozenset((row.id, _utc(row.updated_at)) for row in rows)

    def _check_for_changes(self, now: datetime) -> None:
        """Re-read the schedules if any workflow was added, changed or deleted elsewhere.

        Every change sets ``updated_at`` (or removes the row), so comparing the
        ``(id, updated_at)`` pairs is enough, and that query is small.
        """
        self._last_look = now
        db = self._session()
        try:
            rows = db.query(ProcessWorkflowDb.id, ProcessWorkflowDb.updated_at).all()
            fingerprint = self._fingerprint_of(rows)
        finally:
            db.close()
        if fingerprint != self._fingerprint:
            self._refresh(now)

    def _refresh(self, now: Optional[datetime] = None) -> None:
        """Read the active ``scheduled`` workflows into ``_schedules``."""
        generation = self._generation
        self._last_look = now or self._clock()
        db = self._session()
        try:
            rows = db.query(ProcessWorkflowDb).all()
            self._fingerprint = self._fingerprint_of(rows)
            schedules: Dict[str, _Schedule] = {}
            for row in rows:
                if not row.is_active:
                    continue
                schedule = self._schedule_of(row)
                if schedule is None:
                    continue
                known = self._schedules.get(row.id)
                if known and (known.cron, known.tz, known.changed_at) == (
                    schedule.cron, schedule.tz, schedule.changed_at,
                ):
                    schedule.handled_slot = known.handled_slot
                schedules[row.id] = schedule
            self._schedules = schedules
            if self._generation == generation:
                self._has_scheduled = bool(schedules)
        finally:
            db.close()

    @staticmethod
    def _schedule_of(row: ProcessWorkflowDb) -> Optional[_Schedule]:
        try:
            trigger = json.loads(row.trigger_config or '{}')
        except (TypeError, ValueError):
            return None
        if not isinstance(trigger, dict) or trigger.get('type') != TriggerType.SCHEDULED.value:
            return None
        cron, tz = trigger.get('schedule'), trigger.get('timezone')
        try:
            # Syntax and timezone only: the minimum interval is checked on save, and
            # a short gap at runtime skips that one slot (``_fire``).
            cron = validate_in_app_cron(cron)
            resolve_timezone(tz)
        except QuartzCronError as e:
            # Saved without the validator (older API clients, YAML): never run it.
            logger.warning(
                f"Scheduled workflow {row.id} is not run: invalid schedule ({e.code})"
            )
            return None
        changed_at = _utc(row.updated_at or row.created_at) or datetime.now(timezone.utc)
        return _Schedule(workflow_id=row.id, cron=cron, tz=tz, changed_at=changed_at)

    @staticmethod
    def _due_slot(schedule: _Schedule, now: datetime) -> Optional[datetime]:
        """The latest slot at or before ``now`` if it still has to run."""
        slot = previous_run(schedule.cron, schedule.tz, now)
        if slot is None or slot < schedule.changed_at:
            return None
        if schedule.handled_slot is not None and slot <= schedule.handled_slot:
            return None
        # ``slot`` is the latest one, so it is less than one interval old; the cap
        # keeps e.g. a weekly run from starting days late after downtime.
        if now - slot > MAX_GRACE:
            return None
        return slot

    def _sleep_seconds(self, now: datetime) -> Optional[float]:
        """Seconds until the earliest known deadline, or None when there is none.

        Deadlines: the next slot of every schedule and, when enabled, the idle
        re-check. A periodic task added later (e.g. an expiry sweep) adds its next
        deadline here rather than a fixed tick.
        """
        deadlines: List[datetime] = []
        if self._has_scheduled:
            for schedule in self._schedules.values():
                deadlines.extend(next_runs(schedule.cron, schedule.tz, after=now, count=1))
        if self._idle_recheck > 0 and self._last_look is not None:
            deadlines.append(self._last_look + timedelta(seconds=self._idle_recheck))
        if not deadlines:
            return None
        # Half a second past the deadline, so the wake-up doesn't land just before it.
        return max(0.5, (min(deadlines) - now).total_seconds() + 0.5)

    def _coalesced_slots(
        self, schedule: _Schedule, slot: datetime, last: Optional[datetime],
    ) -> int:
        """How many due slots the run of ``slot`` stands for (1 when nothing was missed)."""
        since = schedule.changed_at - timedelta(microseconds=1)
        if last is not None and last > since:
            since = last
        count = count_runs(schedule.cron, schedule.tz, since, slot, COALESCE_COUNT_LIMIT)
        return max(1, count)

    def _fire(self, schedule: _Schedule, slot: datetime) -> None:
        """Claim ``slot`` and, if this instance got it, run the workflow."""
        from src.common.workflow_executor import WorkflowExecutor
        from src.controller.workflows_manager import WorkflowsManager

        key = task_key(schedule.workflow_id)
        db = self._session()
        claimed = False
        coalesced = 1
        try:
            last = _utc(scheduler_claims_repo.latest_slot(db, task_key=key))
            if last is not None and last < slot and slot - last < MIN_INTERVAL:
                schedule.handled_slot = slot
                if schedule.workflow_id not in self._short_gap_logged:
                    self._short_gap_logged.add(schedule.workflow_id)
                    logger.warning(
                        f"Skipping slots of {key} less than "
                        f"{int(MIN_INTERVAL.total_seconds() // 60)} minutes after the last run"
                    )
                return
            coalesced = self._coalesced_slots(schedule, slot, last)
            claimed = scheduler_claims_repo.claim(
                db, task_key=key, slot=slot, claimed_by=self._claimed_by,
                outcome={'status': 'claimed', 'coalesced_slots': coalesced},
            )
            schedule.handled_slot = slot
            if not claimed:
                logger.info(f"Slot {slot.isoformat()} of {key} was claimed by another instance")
                return
            workflow = WorkflowsManager(db).get_workflow(schedule.workflow_id)
            if workflow is None or not workflow.is_active:
                scheduler_claims_repo.record_outcome(
                    db, task_key=key, slot=slot,
                    outcome={'status': 'skipped', 'coalesced_slots': coalesced},
                )
                return
            scheduled_for = slot.isoformat()
            entity = {
                'type': SCHEDULE_ENTITY_TYPE, 'id': workflow.id, 'name': workflow.name,
                'scheduled_for': scheduled_for,
            }
            context = TriggerContext(
                entity_type=SCHEDULE_ENTITY_TYPE, entity_id=workflow.id,
                entity_name=workflow.name, trigger_type=TriggerType.SCHEDULED,
                user_email=None, entity_data=entity,
            )
            execution = WorkflowExecutor(db).execute_workflow(
                workflow=workflow, entity=entity, entity_type=SCHEDULE_ENTITY_TYPE,
                entity_id=workflow.id, entity_name=workflow.name, user_email=None,
                trigger_context=context, triggered_by=SCHEDULER_USER,
            )
            scheduler_claims_repo.record_outcome(
                db, task_key=key, slot=slot, execution_id=execution.id,
                outcome={
                    'status': execution.status.value, 'coalesced_slots': coalesced,
                    'execution_id': execution.id,
                },
            )
            logger.info(
                f"Ran scheduled workflow {workflow.id} for {scheduled_for}: "
                f"{execution.status.value} (execution {execution.id}, "
                f"{coalesced} slot(s))"
            )
        except Exception as e:
            logger.error(f"Scheduled run of {key} for {slot.isoformat()} failed: {e}",
                         exc_info=True)
            db.rollback()
            if claimed:
                try:
                    scheduler_claims_repo.record_outcome(
                        db, task_key=key, slot=slot,
                        outcome={'status': 'error', 'coalesced_slots': coalesced},
                    )
                except Exception:
                    db.rollback()
        finally:
            db.close()
