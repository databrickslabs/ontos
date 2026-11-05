"""Runs active workflows with a ``scheduled`` trigger (#941).

One thread per app process, like the job poller (``JobsManager.start_background_
polling``). Exactly-once across processes comes from ``scheduler_claims``: for
each due slot every instance inserts ``(workflow:<id>, slot)`` with ``ON CONFLICT
DO NOTHING`` and only the instance whose insert wrote the row runs the workflow.

Database access, so Lakebase can idle:
- While no active workflow has a ``scheduled`` trigger, the thread reads nothing:
  ``_has_scheduled`` stays False until a workflow is created, updated, toggled or
  deleted in this process (``notify_schedules_changed``).
- Otherwise the schedules are kept in memory and the database is read only when a
  slot is due (the definitions are re-read first, which also picks up edits made
  through another instance) or after a local change.

A run gets a synthetic entity ``{type: schedule, id: <workflow id>, scheduled_for}``
and ``triggered_by = system:scheduler``; no user started it, so ``requester``
recipients resolve to nobody. Missed runs are coalesced: after downtime only the
latest slot runs, if it is at most one interval and at most 24 hours old, and its
claim's ``outcome.coalesced_slots`` counts the slots it stands for. A slot before
the workflow's last change is not run, so creating or enabling a workflow doesn't
run a slot that passed before it.
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
    QuartzCronError, count_runs, next_runs, previous_run, validate_schedule,
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

_schedulers: 'weakref.WeakSet[WorkflowScheduler]' = weakref.WeakSet()
_schedulers_lock = threading.Lock()


def notify_schedules_changed() -> None:
    """A workflow changed: the schedulers of this process re-read the scheduled workflows."""
    with _schedulers_lock:
        schedulers = list(_schedulers)
    for scheduler in schedulers:
        scheduler.invalidate()


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
        tick_seconds: int = 60,
        clock: Optional[Callable[[], datetime]] = None,
        instance_id: Optional[str] = None,
    ):
        self._session_factory = session_factory
        self._tick = max(1, int(tick_seconds))
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
        logger.info(f"Started the workflow scheduler (tick: {self._tick}s)")

    def stop(self) -> None:
        if not self._thread or not self._thread.is_alive():
            return
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=10)
        logger.info("Stopped the workflow scheduler")

    def invalidate(self) -> None:
        """Re-read the scheduled workflows on the next tick, and wake the thread."""
        self._has_scheduled = None
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                delay = self.run_once()
            except Exception as e:
                logger.error(f"Workflow scheduler tick failed: {e}", exc_info=True)
                delay = self._tick
            if self._stop.is_set():
                break
            self._wake.wait(timeout=delay)
            self._wake.clear()

    # --- one tick ---------------------------------------------------------------

    def run_once(self, now: Optional[datetime] = None) -> float:
        """Fire the due slots; return the seconds to sleep until the next check."""
        with self._run_lock:
            now = _utc(now) if now else self._clock()
            if self._has_scheduled is None:
                self._refresh()
            if not self._has_scheduled:
                return float(self._tick)
            if any(self._due_slot(s, now) for s in self._schedules.values()):
                self._refresh()  # current definitions before running anything
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

    def _refresh(self) -> None:
        """Read the active ``scheduled`` workflows into ``_schedules``."""
        db = self._session()
        try:
            rows = db.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.is_active.is_(True)).all()
            schedules: Dict[str, _Schedule] = {}
            for row in rows:
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
            cron = validate_schedule(cron, tz)
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

    def _sleep_seconds(self, now: datetime) -> float:
        upcoming: List[datetime] = []
        for schedule in self._schedules.values():
            upcoming.extend(next_runs(schedule.cron, schedule.tz, after=now, count=1))
        if not upcoming:
            return float(self._tick)
        # Half a second past the slot, so the wake-up doesn't land just before it.
        until_next = (min(upcoming) - now).total_seconds() + 0.5
        return max(0.5, min(float(self._tick), until_next))

    def _coalesced_slots(self, db: Session, schedule: _Schedule, slot: datetime) -> int:
        """How many due slots the run of ``slot`` stands for (1 when nothing was missed)."""
        since = schedule.changed_at - timedelta(microseconds=1)
        last = _utc(scheduler_claims_repo.latest_slot(db, task_key=task_key(schedule.workflow_id)))
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
            coalesced = self._coalesced_slots(db, schedule, slot)
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
