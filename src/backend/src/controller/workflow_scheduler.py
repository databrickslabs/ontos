"""Runs active workflows with a ``scheduled`` trigger (#941).

One thread per app process, like the job poller (``JobsManager.start_background_
polling``), claims the due slots; the runs go to a small pool of daemon threads
(``max_workers``), each with its own session, so a long run doesn't hold up the
other scheduled workflows. A workflow whose previous run is still going on this
instance waits for it before its next slot is claimed. A run queued behind busy
workers that can only start after the workflow's next slot (or more than 24 hours
late) is not started: its claim gets ``skipped`` with ``reason: late``.

Connections: in the app, the scheduler and its runs use an engine of their own
with ``max_workers + 1`` connections and no overflow (``start()``), so long runs
can't take the request pool's connections (``DB_POOL_SIZE`` +
``DB_MAX_OVERFLOW``); an instance opens at most that many more connections. One
exception: after an in-process restart (the startup retry stops the scheduler and
starts a new one, or ``stop()`` then ``start()``), a run still going after the
drain keeps its connection of the old, disposed engine until it ends, on top of
the new engine's.

Each slot runs at most once across processes, through ``scheduler_claims``: for
each due slot every instance inserts ``(workflow:<id>, slot)`` with ``ON CONFLICT
DO NOTHING`` and only the instance whose insert wrote the row runs the workflow.
The claim is committed before the run starts, so if the process dies in between
or during the run, that slot isn't run again: its claim stays ``claimed`` (no
outcome). ``stop()`` waits up to ``drain_seconds`` for the runs in progress and
records the runs it didn't start as ``not_started``; a slot claimed while it stops
is recorded the same way, never started. The pool's threads are daemon threads,
so a run still going after the drain doesn't keep the process from exiting.
Claims of slots older than ``CLAIM_RETENTION`` are deleted (the latest one of
each workflow is kept), at most once a day, right after a claim.

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

Overdue approval steps (#1119, ``approval_timeouts_manager``) are looked for on the
first pass and when a request (the database is awake) notes that a new
``APPROVAL_TIMEOUTS_INTERVAL`` slot began, at most once per slot across instances
(claimed as ``approval-timeouts``): no timer of its own.

Missed runs are coalesced: after downtime only the latest slot runs, if it is at
most one interval and at most 24 hours old, and its claim's
``outcome.coalesced_slots`` counts the slots it stands for. A slot before the
workflow's last schedule change (``schedule_changed_at``: the trigger's type, cron
or timezone, or ``is_active``) is not run, so creating or enabling a workflow
doesn't run a slot that passed before it; other edits and restarts keep the slot.

The same thread delivers the delivery outbox's pending rows (#1688,
``delivery_outbox_manager.DeliveryOutboxWorker``): on the first pass, when a request
notes a new sweep slot, and when the next pending row it knows of is due (a
deadline in ``_sleep_seconds``); with no pending row it adds no deadline. With
``WORKFLOW_SCHEDULER_ENABLED`` off the thread still runs for the outbox only
(``run_workflows=False``): no workflow is read or run.
"""
import json
import os
import queue
import socket
import threading
import time
import weakref
from concurrent.futures import Executor, Future
from concurrent.futures import wait as wait_futures
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.quartz_cron import (
    MIN_INTERVAL, QuartzCronError, count_runs, next_runs, previous_run, resolve_timezone,
    validate_in_app_cron,
)
from src.controller.delivery_outbox_manager import DeliveryOutboxWorker
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
# Scheduled runs run on a pool, so one long run doesn't hold up the other workflows.
DEFAULT_MAX_WORKERS = 4
# On shutdown, wait this long for the runs in progress to end.
DEFAULT_DRAIN_SECONDS = 30
# Claims of older slots are deleted (the latest one of each task is kept) ...
CLAIM_RETENTION = timedelta(days=30)
# ... at most this often per instance, after a claim (the database is awake then).
PRUNE_INTERVAL = timedelta(hours=24)
# Overdue approval steps (#1119) are looked for at most once per slot of this length,
# across instances (claimed like a scheduled run), and only while the database is awake.
APPROVAL_TIMEOUTS_TASK_KEY = 'approval-timeouts'
APPROVAL_TIMEOUTS_INTERVAL = timedelta(minutes=15)

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
        scheduler.note_outbox_activity()


def notify_delivery_queued(when: datetime) -> None:
    """A delivery outbox row of this instance is due at ``when`` (#1688): the
    schedulers of this process deliver it then."""
    with _schedulers_lock:
        schedulers = list(_schedulers)
    for scheduler in schedulers:
        scheduler.note_delivery_queued(when)


def task_key(workflow_id: str) -> str:
    return f'{TASK_KEY_PREFIX}{workflow_id}'


class _DaemonPool(Executor):
    """A fixed-size pool of daemon threads.

    ``ThreadPoolExecutor``'s threads are joined at interpreter exit, so a run
    still going after the drain would hold up the exit until it ends. These
    threads don't: the exit cuts the run off, and its claim stays ``claimed``.
    """

    def __init__(self, max_workers: int, name: str):
        self._max_workers = max(1, int(max_workers))
        self._name = name
        self._queue: 'queue.SimpleQueue' = queue.SimpleQueue()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()
        self._shut_down = False

    def submit(self, fn, /, *args, **kwargs) -> Future:
        with self._lock:
            if self._shut_down:
                raise RuntimeError('cannot schedule new runs after shutdown')
            future: Future = Future()
            self._queue.put((future, fn, args, kwargs))
            if len(self._threads) < self._max_workers:
                thread = threading.Thread(
                    target=self._work, daemon=True,
                    name=f'{self._name}_{len(self._threads)}',
                )
                self._threads.append(thread)
                thread.start()
        return future

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, fn, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = fn(*args, **kwargs)
            except BaseException as e:  # noqa: BLE001 - handed to the future
                future.set_exception(e)
            else:
                future.set_result(result)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        with self._lock:
            self._shut_down = True
            threads = list(self._threads)
        for _ in threads:
            self._queue.put(None)
        if wait:
            for thread in threads:
                thread.join()


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

    # stop() waits this long for the scheduler thread before draining.
    _stop_join_seconds: float = 10

    def __init__(
        self,
        session_factory: Optional[Callable[[], Session]] = None,
        *,
        deliver_outbox: bool = True,
        run_workflows: bool = True,
        change_check_seconds: int = 60,
        idle_recheck_seconds: int = 0,
        clock: Optional[Callable[[], datetime]] = None,
        instance_id: Optional[str] = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
        run_executor: Optional[Executor] = None,
        drain_seconds: float = DEFAULT_DRAIN_SECONDS,
        remind_overdue_approvals: bool = True,
    ):
        self._drain_seconds = max(0.0, float(drain_seconds))
        # Look for overdue approval steps on the passes that read the database (#1119)
        self._remind_overdue = remind_overdue_approvals
        self._session_factory = session_factory
        # Runs go to this pool; the scheduler thread only claims slots.
        self._max_workers = max(1, int(max_workers))
        self._pool: Optional[Executor] = run_executor
        # Guards ``_pool``, ``_closing`` and the registration of submitted runs.
        self._pool_lock = threading.Lock()
        # Set by drain(): a slot claimed from then on is not started (not_started).
        self._closing = False
        # The engine start() made for the scheduler's sessions; disposed by stop().
        self._own_engine = None
        # When this instance last deleted old claims.
        self._last_prune: Optional[datetime] = None
        # The last slot this instance looked for overdue approvals in (claimed or not).
        self._timeouts_slot: Optional[datetime] = None
        # Set by a request when a new slot began: the next pass looks (#1119).
        self._timeouts_requested = False
        # Workflow id -> the future of its run in progress on this instance.
        self._in_flight: Dict[str, Future] = {}
        # Future -> (task key, slot, coalesced count) of that run, for the drain.
        self._runs: Dict[Future, tuple] = {}
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
        # Workflows already reported as never running again (logged once each).
        self._no_run_logged: set = set()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._claimed_by = instance_id or f'{socket.gethostname()}:{os.getpid()}'
        # Delivers the delivery outbox's pending rows from this thread (#1688)
        self._outbox = DeliveryOutboxWorker(self._clock) if deliver_outbox else None
        # False (WORKFLOW_SCHEDULER_ENABLED off): the thread only delivers the outbox
        self._run_workflows = run_workflows
        self._schedules: Dict[str, _Schedule] = {}
        # None = unknown (read the database on the next tick); False = no active
        # scheduled workflow (no database access); True = ``_schedules`` is current.
        self._has_scheduled: Optional[bool] = None
        self._run_lock = threading.Lock()
        # ``time.monotonic()`` when the current pass began: the budget of a run to start
        # (``_start_budget``) is measured from the pass's ``now``, so it ends at the same
        # instant however long the claims before this one took.
        self._pass_started: Optional[float] = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        with _schedulers_lock:
            _schedulers.add(self)

    # --- thread -----------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive() and not self._stop.is_set():
            logger.warning("Workflow scheduler already running")
            return
        if self._thread and self._thread.is_alive():
            # A stop() whose thread outlived the join (a slow pass): that thread ends
            # after its pass, with its own stop event; a new one takes over.
            logger.warning("Workflow scheduler: the stopped thread is still in its "
                           "last pass; starting a new one")
        # A new event per thread, so restarting doesn't revive the old thread.
        self._stop = threading.Event()
        with self._pool_lock:
            self._closing = False
        self._use_dedicated_engine()
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
        self._thread.join(timeout=self._stop_join_seconds)
        self.drain()
        self._dispose_own_engine()
        logger.info("Stopped the workflow scheduler")

    def _use_dedicated_engine(self) -> None:
        """Without an injected session factory, use an engine of its own (see the module doc).

        ``max_workers`` runs plus the scheduler thread: nobody waits for a connection.
        Without the app's engine (tests) the app's session factory is used.
        """
        if self._session_factory is not None:
            return
        from src.common.database import create_dedicated_session_factory

        try:
            created = create_dedicated_session_factory(
                self._max_workers + 1, 'workflow_scheduler')
        except Exception as e:
            # Only the exception class: a database error text can carry the connection URL.
            logger.warning(
                "Workflow scheduler: could not create its own database engine "
                f"({type(e).__name__}); falling back to the app's connection pool")
            return
        if created is None:
            logger.warning(
                "Workflow scheduler: the app's database engine is not set up or its session "
                "factory was replaced; using the app's connection pool")
            return
        self._session_factory, self._own_engine = created

    def _dispose_own_engine(self) -> None:
        engine, self._own_engine = self._own_engine, None
        if engine is None:
            return
        self._session_factory = None
        try:
            engine.dispose()
        except Exception as e:
            logger.warning(f"Could not dispose the workflow scheduler's engine: {e}")

    def drain(self, timeout: Optional[float] = None) -> None:
        """Stop starting runs: cancel the queued ones, wait for the ones in progress.

        A queued run that never started gets the outcome ``not_started``. A run
        still going after ``timeout`` (default ``drain_seconds``) is left to end on
        its own; if the process exits first, its claim stays ``claimed``.

        From here on a claimed slot isn't handed to the pool (``not_started``),
        so a pass still going (a slow claim) can't start a run during the exit;
        ``start()`` makes the object usable again, with a new pool.
        """
        with self._pool_lock:
            self._closing = True
            runs = list(self._runs)
        for future in runs:
            if future.cancel():
                key, slot, coalesced = self._runs.pop(future, (None, None, None))
                if key is not None:
                    self._record(key, slot, {
                        'status': 'not_started', 'coalesced_slots': coalesced,
                    })
        timeout = self._drain_seconds if timeout is None else timeout
        if not self.wait_for_runs(timeout=timeout):
            logger.warning(
                f"{len(self._in_flight)} scheduled run(s) still in progress after "
                f"{timeout:g} s; a run cut off by the exit is not run again"
            )
        with self._pool_lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False)

    def invalidate(self) -> None:
        """Re-read the scheduled workflows now: wake the thread."""
        self._generation += 1
        self._has_scheduled = None
        self._wake.set()

    def note_database_activity(self) -> None:
        """The database is awake: check for changes made elsewhere, unless one was just made.

        Also, once per ``APPROVAL_TIMEOUTS_INTERVAL`` slot, look for overdue approvals
        (whatever the state of the schedules): see ``_remind_overdue_approvals``.
        """
        last = self._timeouts_slot
        if self._remind_overdue and not self._timeouts_requested and (
            last is None or self._timeouts_slot_of(self._clock()) > last
        ):
            self._timeouts_requested = True
            self._wake.set()
        if self._change_check_requested or self._has_scheduled is None:
            return
        last = self._last_look
        if last is not None and self._clock() - last < self._change_check:
            return
        self._change_check_requested = True
        self._wake.set()

    def _loop(self) -> None:
        stop = self._stop  # this thread's event: start() gives a new thread a new one
        while not stop.is_set():
            # Cleared before the pass, so a wake-up during it isn't lost.
            self._wake.clear()
            try:
                delay = self._tick()
            except Exception as e:
                logger.error(f"Workflow scheduler pass failed: {e}", exc_info=True)
                delay = ERROR_RETRY_SECONDS
            if stop.is_set():
                break
            self._wake.wait(timeout=delay)  # None: until woken

    # --- one tick ---------------------------------------------------------------

    def run_once(self, now: Optional[datetime] = None) -> Optional[float]:
        """Fire the due slots; return the seconds until the next deadline (None: none)."""
        with self._run_lock:
            self._pass_started = time.monotonic()
            explicit_now = now
            now = _utc(now) if now else self._clock()
            check_requested, self._change_check_requested = self._change_check_requested, False
            timeouts_requested, self._timeouts_requested = self._timeouts_requested, False
            first_look = self._has_scheduled is None
            if first_look:
                self._refresh(now)
            elif check_requested or self._idle_recheck_due(now):
                self._check_for_changes(now)
            if first_look or timeouts_requested:
                self._remind_overdue_approvals(now)
            if self._has_scheduled and any(
                self._due_slot(s, now) for s in self._schedules.values()
            ):
                self._refresh(now)  # current definitions before running anything
                retry = False
                for schedule in list(self._schedules.values()):
                    if schedule.workflow_id in self._in_flight:
                        # Its previous run is still going: the slot waits for it (the
                        # run's end wakes the thread), within the grace period.
                        continue
                    slot = self._due_slot(schedule, now)
                    if slot is not None and not self._fire(schedule, slot, now):
                        retry = True
                # Claims take time: sleep from the time now, not the pass's start.
                now = self._clock() if explicit_now is None else now
                delay = self._sleep_seconds(now)
                if retry and (delay is None or delay > ERROR_RETRY_SECONDS):
                    # A slot failed before its claim: try it again soon (the grace
                    # period still applies), not only at the next slot.
                    return float(ERROR_RETRY_SECONDS)
                return delay
            return self._sleep_seconds(now)

    @staticmethod
    def _timeouts_slot_of(now: datetime) -> datetime:
        interval = APPROVAL_TIMEOUTS_INTERVAL.total_seconds()
        return datetime.fromtimestamp(now.timestamp() // interval * interval, tz=timezone.utc)

    def _remind_overdue_approvals(self, now: datetime) -> None:
        """Remind the overdue approval steps (#1119), once per slot across instances.

        On the first pass and when a request (the database is awake) notes that a new
        slot began: no timer of its own, so an idle Lakebase stays idle.
        A reminder is in-app, seen when the app is used. Failures are only logged.

        The same slot applies the decisions of ended access workflows that couldn't be
        recorded on their request (``AccessGrantsManager.reconcile_workflow_decisions``).
        """
        from src.controller.access_grants_manager import AccessGrantsManager
        from src.controller.approval_timeouts_manager import remind_overdue_approvals

        if not self._remind_overdue:
            return
        slot = self._timeouts_slot_of(now)
        if self._timeouts_slot is not None and slot <= self._timeouts_slot:
            return
        self._timeouts_slot = slot
        db = self._session()
        try:
            if not scheduler_claims_repo.claim(
                db, task_key=APPROVAL_TIMEOUTS_TASK_KEY, slot=slot,
                claimed_by=self._claimed_by, outcome={'status': 'claimed'},
            ):
                return  # another instance looks in this slot
            reminded = remind_overdue_approvals(db, now)
            try:
                reconciled = AccessGrantsManager().reconcile_workflow_decisions(db, now)
            except Exception as e:
                logger.error(f"Reconciling access workflow decisions failed: {e}", exc_info=True)
                db.rollback()
                reconciled = None
            scheduler_claims_repo.record_outcome(
                db, task_key=APPROVAL_TIMEOUTS_TASK_KEY, slot=slot,
                outcome={'status': 'done', 'reminded': reminded, 'reconciled': reconciled},
            )
        except Exception as e:
            logger.error(f"Looking for overdue approvals failed: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

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
                self._warn_if_never_runs(schedule, self._last_look)
                known = self._schedules.get(row.id)
                if known and (known.cron, known.tz, known.changed_at) == (
                        schedule.cron, schedule.tz, schedule.changed_at):
                    schedule.handled_slot = known.handled_slot
                schedules[row.id] = schedule
            self._schedules = schedules
            if self._generation == generation:
                self._has_scheduled = bool(schedules)
        finally:
            db.close()

    def _warn_if_never_runs(self, schedule: _Schedule, now: datetime) -> None:
        """Log once that a stored schedule has no run left (e.g. only past years).

        Saves refuse it (``cron_no_upcoming_runs``), but the API before that check
        or a YAML file can store one; it isn't an error, it just never runs.
        """
        if schedule.workflow_id in self._no_run_logged:
            return
        if next_runs(schedule.cron, schedule.tz, after=now, count=1):
            return
        self._no_run_logged.add(schedule.workflow_id)
        logger.warning(
            f"Scheduled workflow {schedule.workflow_id} is not run: its schedule has no "
            "upcoming run (cron_no_upcoming_runs)"
        )

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
        # Only a change of the schedule or of ``is_active`` moves the cutoff: an edit
        # of anything else (name, steps, ...) after a slot, or a restart, keeps it.
        changed_at = _utc(
            row.schedule_changed_at or row.created_at
        ) or datetime.now(timezone.utc)
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
        outbox_due = self._outbox.next_deadline() if self._outbox is not None else None
        if outbox_due is not None:
            deadlines.append(outbox_due)
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

    def _fire(self, schedule: _Schedule, slot: datetime,
              now: Optional[datetime] = None) -> bool:
        """Claim ``slot`` and, if this instance got it, hand the run to the pool.

        Returns False when it failed before the claim was written (e.g. a
        transient database error): the slot is not handled and is tried again.
        After the claim, a failure is recorded as the outcome ``error`` and the
        slot is not run again.
        """
        now = now or self._clock()
        key = task_key(schedule.workflow_id)
        db = self._session()
        try:  # the session is closed on every path: it may be one of few connections
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
                    return True
                coalesced = self._coalesced_slots(schedule, slot, last)
                claimed = scheduler_claims_repo.claim(
                    db, task_key=key, slot=slot, claimed_by=self._claimed_by,
                    outcome={'status': 'claimed', 'coalesced_slots': coalesced},
                )
            except Exception as e:
                logger.error(
                    f"Claiming {key} for {slot.isoformat()} failed: {e}", exc_info=True)
                db.rollback()
                return False  # nothing written: run_once retries the slot
            if claimed:
                self._prune_claims(db, now)
        finally:
            db.close()
        schedule.handled_slot = slot
        if not claimed:
            logger.info(f"Slot {slot.isoformat()} of {key} was claimed by another instance")
            return True
        workflow_id = schedule.workflow_id
        # From the pass's start, not from now: the claims before this one took time that
        # the run's budget (counted from the pass's ``now``) must not get back.
        started = self._pass_started if self._pass_started is not None else time.monotonic()
        start_by = started + self._start_budget(schedule, slot, now)
        failed: Optional[str] = None
        # Submitted and registered under the lock drain() takes to set ``_closing``:
        # either drain() sees the run (and cancels it if queued) or it is never submitted.
        with self._pool_lock:
            if self._closing:
                failed = 'not_started'
            else:
                try:
                    future = self._executor_locked().submit(
                        self._run, workflow_id, slot, coalesced, start_by=start_by)
                except Exception as e:  # e.g. the pool is shut down
                    logger.error(
                        f"Could not start the run of {key} for {slot.isoformat()}: {e}")
                    failed = 'error'
                else:
                    self._in_flight[workflow_id] = future
                    self._runs[future] = (key, slot, coalesced)
        if failed is not None:
            if failed == 'not_started':
                logger.info(f"Not starting {key} for {slot.isoformat()}: the scheduler stops")
            self._record(key, slot, {'status': failed, 'coalesced_slots': coalesced})
            return True
        # Called at once if the run already ended.
        future.add_done_callback(lambda f, wid=workflow_id: self._run_ended(wid, f))
        return True

    @staticmethod
    def _start_budget(schedule: _Schedule, slot: datetime, now: datetime) -> float:
        """Seconds from ``now`` the run of ``slot`` may still start in.

        Until the workflow's next slot (that one runs instead) and at most
        ``MAX_GRACE`` after ``slot``, the grace the claim itself applies.
        """
        latest = slot + MAX_GRACE
        upcoming = next_runs(schedule.cron, schedule.tz, after=slot, count=1)
        if upcoming and upcoming[0] < latest:
            latest = upcoming[0]
        return (latest - now).total_seconds()

    def _prune_claims(self, db: Session, now: datetime) -> None:
        """Delete old claims, at most once per ``PRUNE_INTERVAL``; failures are only logged."""
        if self._last_prune is not None and now - self._last_prune < PRUNE_INTERVAL:
            return
        self._last_prune = now
        try:
            deleted = scheduler_claims_repo.prune(db, before=now - CLAIM_RETENTION)
        except Exception as e:
            logger.warning(f"Could not delete old scheduler claims: {e}")
            db.rollback()
            return
        if deleted:
            logger.info(f"Deleted {deleted} scheduler claim(s) older than "
                        f"{CLAIM_RETENTION.days} days")

    def wait_for_runs(self, timeout: Optional[float] = None) -> bool:
        """Wait until the runs in progress on this instance end; False on a timeout."""
        _, pending = wait_futures(list(self._in_flight.values()), timeout=timeout)
        return not pending

    def _executor_locked(self) -> Executor:
        """The run pool, created on first use; the caller holds ``_pool_lock``."""
        if self._pool is None:
            self._pool = _DaemonPool(self._max_workers, 'WorkflowRun')
        return self._pool

    def _run_ended(self, workflow_id: str, future: Optional[Future] = None) -> None:
        self._in_flight.pop(workflow_id, None)
        if future is not None and not future.cancelled():
            self._runs.pop(future, None)
        self._wake.set()  # a slot that waited for this run can go now

    def _record(self, key: str, slot: datetime, outcome: dict,
                execution_id: Optional[str] = None) -> None:
        db = self._session()
        try:
            scheduler_claims_repo.record_outcome(
                db, task_key=key, slot=slot, outcome=outcome, execution_id=execution_id,
            )
        except Exception as e:
            logger.error(f"Could not record the outcome of {key} for {slot.isoformat()}: {e}")
            db.rollback()
        finally:
            db.close()

    def _run(self, workflow_id: str, slot: datetime, coalesced: int,
             start_by: Optional[float] = None) -> None:
        """Run a claimed slot (on the pool, with its own session) and record its outcome.

        ``start_by`` (``time.monotonic()``): a run that only gets a worker later
        is not started, so a queued run doesn't start hours late.
        """
        from src.common.workflow_executor import WorkflowExecutor
        from src.controller.workflows_manager import WorkflowsManager

        key = task_key(workflow_id)
        db = self._session()
        try:
            if start_by is not None and time.monotonic() > start_by:
                logger.warning(
                    f"Not starting {key} for {slot.isoformat()}: it waited for a worker "
                    "past its next slot (or 24 hours)"
                )
                scheduler_claims_repo.record_outcome(
                    db, task_key=key, slot=slot,
                    outcome={'status': 'skipped', 'reason': 'late',
                             'coalesced_slots': coalesced},
                )
                return
            workflow = WorkflowsManager(db).get_workflow(workflow_id)
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
            try:
                scheduler_claims_repo.record_outcome(
                    db, task_key=key, slot=slot,
                    outcome={'status': 'error', 'coalesced_slots': coalesced},
                )
            except Exception:
                db.rollback()
        finally:
            db.close()

    # --- delivery outbox (#1688) ----------------------------------------------------

    def note_outbox_activity(self) -> None:
        """A request uses the database: look for due outbox rows once per sweep slot."""
        if self._outbox is not None and self._outbox.note_activity():
            self._wake.set()

    def note_delivery_queued(self, when: datetime) -> None:
        """An outbox row of this instance is due at ``when``: wake up then."""
        if self._outbox is None:
            return
        self._outbox.note_queued(when)
        self._wake.set()  # the sleep is recomputed with the new deadline

    def _tick(self) -> Optional[float]:
        """One pass of the thread: the outbox, then the scheduled workflows unless they
        are off; the seconds until the next deadline (None: none)."""
        self.run_outbox()
        if not self._run_workflows:
            return self._sleep_seconds(self._clock())
        return self.run_once()

    def run_outbox(self, now: Optional[datetime] = None) -> int:
        """Deliver the due outbox rows when a pass is due; the rows tried."""
        now = _utc(now) if now else self._clock()
        if self._outbox is None or not self._outbox.due(now):
            return 0
        try:
            return self._outbox.run(self._session, now, claimed_by=self._claimed_by)
        except Exception as e:
            logger.error(f"Delivery outbox pass failed: {e}", exc_info=True)
            return 0
