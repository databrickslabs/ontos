"""
Metadata Generation manager.

A Generation Run runs the ``metagen_generate`` background job (dbxmetagen in
comment mode) over a selection of UC objects. The job writes normalized rows
to the Delta table ``<DATABRICKS_CATALOG>.<DATABRICKS_SCHEMA>.metagen_results``;
when the job finishes, this manager ingests them as Description Suggestions.

Run status is derived from the Jobs API, refreshed on demand by the run page
and by the JobsManager background poller (see ``handle_job_terminated``).
See docs/decisions/metadata-generation-execution.md.
"""

import threading
import time
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from src.common.config import Settings, resolve_volume
from src.common.errors import ConflictError
from src.common.logging import get_logger
from src.db_models.metadata_generation import DescriptionSuggestionDb, MetadataGenerationRunDb
from src.models.metadata_generation import (
    TERMINAL_RUN_STATUSES,
    GenerationRunStatus,
    StartRunRequest,
    SuggestionStatus,
)
from src.repositories.metadata_generation_repository import (
    metagen_runs_repo,
    metagen_suggestions_repo,
)

logger = get_logger(__name__)

WORKFLOW_ID = "metagen_generate"
RESULTS_TABLE = "metagen_results"
# Rows per results query; keeps each response well below the 25 MiB inline limit
RESULTS_PAGE_SIZE = 2000
DEFAULT_MODEL = "databricks-claude-sonnet-4-6"
MAX_ACTIVE_RUNS_PER_USER = 1
# An ingest claim older than this is treated as abandoned (e.g. the app restarted)
STALE_INGEST_CLAIM = timedelta(minutes=15)
# Loading a successful job's results is retried this often before the run fails
MAX_INGEST_ATTEMPTS = 3
# Wait before retrying a failed ingest: this, doubled per further attempt
INGEST_RETRY_DELAY = timedelta(minutes=1)
# A run is given up on when its job status can't be read although the job
# must have ended (its own timeout is 2h) and reads have kept failing a while
JOB_STATUS_GIVE_UP = timedelta(hours=2, minutes=30)
JOB_STATUS_UNAVAILABLE_FOR = timedelta(minutes=30)
# How long a queued-ingest marker suppresses queueing the same run again
QUEUED_INGEST_TTL = STALE_INGEST_CLAIM

# Jobs API life-cycle states after which a run will not change any more
_TERMINAL_LIFE_CYCLE_STATES = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}


class ActiveRunLimitError(ValueError):
    """The user already has the maximum number of runs in flight."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def selections_overlap(a: str, b: str) -> bool:
    """Whether two ``cat[.sch[.tbl]]`` names cover a common table."""
    a, b = a.lower(), b.lower()
    return a == b or a.startswith(b + ".") or b.startswith(a + ".")


def selection_to_table_names(selection: List[Dict[str, str]]) -> List[str]:
    """Flatten a selection into the ``cat[.sch[.tbl]]`` names the job expands."""
    names: List[str] = []
    for item in selection:
        fqn = (item.get("fqn") or "").strip()
        expected_parts = {"catalog": 1, "schema": 2, "table": 3}[item["type"]]
        if fqn.count(".") + 1 != expected_parts:
            raise ValueError(f"'{fqn}' is not a valid {item['type']} name")
        names.append(fqn)
    return names


class MetadataGenerationManager:

    def __init__(
        self,
        *,
        settings: Settings,
        jobs_manager: Any = None,
        workspace_client_factory: Optional[Callable[[], Any]] = None,
        ingest_executor: Optional[Executor] = None,
    ):
        self._settings = settings
        self._jobs = jobs_manager
        self._ws_factory = workspace_client_factory
        # Ingests started from the jobs poller run here, so a slow warehouse
        # read doesn't stall polling for every other workflow
        self._ingest_executor = ingest_executor or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="metagen-ingest"
        )
        # Runs with an ingest queued or in progress in this process (run id ->
        # time.monotonic() when queued), so the poller, the sweep and page polls
        # don't queue the same run repeatedly. Markers expire, so one whose task
        # never ran (its request failed after deferring) can't block the run.
        self._queued_ingests: Dict[str, float] = {}
        self._queued_lock = threading.Lock()
        self._submit_ingest = self.make_deferrer(self._ingest_executor.submit)
        if self._jobs is not None and hasattr(self._jobs, "register_run_terminated_handler"):
            self._jobs.register_run_terminated_handler(WORKFLOW_ID, self.handle_job_terminated)
            # Each poller cycle also retries runs a one-off notification can't
            # finish: a failed ingest attempt, an abandoned claim, an orphan
            self._jobs.register_poll_cycle_handler(self.sweep_active_runs)

    def make_deferrer(self, schedule: Callable[..., Any]) -> Callable[[str], None]:
        """A ``defer_ingest`` callback that queues each run at most once at a time.

        ``schedule(fn, run_id)`` runs ``fn(run_id)`` later, e.g. an executor's
        ``submit`` or FastAPI's ``BackgroundTasks.add_task``.
        """
        def defer(run_id: str) -> None:
            with self._queued_lock:
                queued_at = self._queued_ingests.get(run_id)
                if queued_at is not None and time.monotonic() - queued_at < QUEUED_INGEST_TTL.total_seconds():
                    return
                self._queued_ingests[run_id] = time.monotonic()
            try:
                schedule(self._run_queued_ingest, run_id)
            except Exception:
                self._release_queued(run_id)
                raise

        return defer

    def _run_queued_ingest(self, run_id: str) -> None:
        try:
            self.ingest_run_by_id(run_id)
        finally:
            self._release_queued(run_id)

    def _release_queued(self, run_id: str) -> None:
        with self._queued_lock:
            self._queued_ingests.pop(run_id, None)

    def sweep_active_runs(self, db: Session) -> None:
        """Poll-cycle hook: finish or retry active runs, ingesting off the poller thread."""
        self._refresh_active_runs(db, defer_ingest=self._submit_ingest)

    def _output_schema(self) -> Tuple[str, str]:
        """The app's deploy-time catalog and schema.

        Databricks Apps deployments inject the volume path (its catalog and
        schema win); bundle and local deployments set DATABRICKS_CATALOG /
        DATABRICKS_SCHEMA. A volume that isn't a UC volume (a local path in
        development) doesn't name a schema.
        """
        try:
            resolved = resolve_volume(self._settings)
        except ValueError:
            resolved = None
        if resolved:
            return resolved[0], resolved[1]
        return self._settings.DATABRICKS_CATALOG, self._settings.DATABRICKS_SCHEMA

    # ------------------------------------------------------------------
    # Start / cancel / delete
    # ------------------------------------------------------------------
    def start_run(
        self,
        db: Session,
        *,
        user_id: str,
        request: StartRunRequest,
        defer_ingest: Optional[Callable[[str], None]] = None,
    ) -> MetadataGenerationRunDb:
        """Create a Generation Run and launch the background job.

        ``defer_ingest`` is passed on to the refresh of active runs, so a
        finished run's ingest doesn't run inside this request.
        """
        active = self._refresh_active_runs(db, defer_ingest=defer_ingest)
        if sum(1 for r in active if r.user_id == user_id) >= MAX_ACTIVE_RUNS_PER_USER:
            raise ActiveRunLimitError("You already have a Generation Run in progress. Wait for it to finish or cancel it.")
        selection = [item.model_dump() for item in request.selection]
        table_names = selection_to_table_names(selection)
        if not self._jobs:
            raise ValueError("Jobs manager not available")
        self._check_no_overlapping_run(active, table_names)

        from src.repositories.workflow_installations_repository import workflow_installation_repo
        installation = workflow_installation_repo.get_by_workflow_id(db=db, workflow_id=WORKFLOW_ID)
        if not installation:
            raise ConflictError(
                "The Metadata Generation background job is not enabled. "
                "Ask an administrator to enable it under Settings > Jobs."
            )

        model = request.model or self._settings.LLM_ENDPOINT or DEFAULT_MODEL
        options = {
            "comment_style": request.comment_style.value,
            "model": model,
            # Data sampling stays off until the admin-gated toggle lands (#1188)
            "allow_data": False,
            "sample_size": 0,
            "regenerate_existing": request.regenerate_existing,
            "auto_submit": request.auto_submit,
        }

        run = metagen_runs_repo.create(db, user_id=user_id, selection=selection, options=options)
        db.commit()

        output_catalog, output_schema = self._output_schema()
        job_params = {
            "ontos_run_id": run.id,
            "table_names": ",".join(table_names),
            "output_catalog": output_catalog,
            "output_schema": output_schema,
            "model": model,
            "comment_style": options["comment_style"],
            "allow_data": "false",
            "sample_size": "0",
            "regenerate_existing": str(request.regenerate_existing).lower(),
        }
        try:
            job_run_id = self._jobs.run_job(
                job_id=int(installation.job_id),
                job_name=WORKFLOW_ID,
                workflow_id=WORKFLOW_ID,
                job_parameters=job_params,
            )
        except Exception as e:
            logger.error("Failed to launch metadata generation job for run %s: %s", run.id, e, exc_info=True)
            run.status = GenerationRunStatus.FAILED.value
            run.error = "Failed to start the background job"
            run.completed_at = _now()
            db.commit()
            raise

        run.job_run_id = str(job_run_id)
        run.status = GenerationRunStatus.RUNNING.value
        run.started_at = _now()
        run.progress_message = "Generating descriptions"
        db.commit()
        db.refresh(run)
        return run

    def _check_no_overlapping_run(self, active: List[MetadataGenerationRunDb], table_names: List[str]) -> None:
        """Reject a run whose objects an active run is already describing.

        dbxmetagen's log carries no run id, so the job attributes its rows by
        table and time; two concurrent runs over the same table could pick up
        each other's output.
        """
        for other in active:
            for item in other.selection or []:
                for name in table_names:
                    if selections_overlap(name, item.get("fqn", "")):
                        raise ConflictError(
                            f"Another Generation Run is already describing objects in {item['fqn']}. "
                            "Wait for it to finish or cancel it."
                        )

    def cancel_run(self, db: Session, run: MetadataGenerationRunDb) -> MetadataGenerationRunDb:
        if run.status in TERMINAL_RUN_STATUSES:
            raise ValueError(f"Run is already {run.status}")
        if run.status == GenerationRunStatus.INGESTING.value:
            raise ValueError("The job has finished and its results are being loaded")
        if run.job_run_id and self._jobs:
            self._jobs.cancel_run(int(run.job_run_id))
        run.status = GenerationRunStatus.CANCELLED.value
        run.progress_message = None
        run.completed_at = _now()
        db.commit()
        db.refresh(run)
        return run

    def delete_run(self, db: Session, run: MetadataGenerationRunDb) -> None:
        if run.status not in TERMINAL_RUN_STATUSES:
            raise ValueError("Cancel the run before deleting it")
        in_review = (
            db.query(DescriptionSuggestionDb.id)
            .filter(
                DescriptionSuggestionDb.run_id == run.id,
                DescriptionSuggestionDb.review_request_id.isnot(None),
                DescriptionSuggestionDb.status.in_((SuggestionStatus.PENDING.value, SuggestionStatus.ACCEPTED.value)),
            )
            .first()
        )
        if in_review:
            raise ValueError("The run has suggestions in an open review")
        metagen_runs_repo.delete(db, run)
        db.commit()

    # ------------------------------------------------------------------
    # Status refresh
    # ------------------------------------------------------------------
    def refresh_run(
        self,
        db: Session,
        run: MetadataGenerationRunDb,
        *,
        defer_ingest: Optional[Callable[[str], None]] = None,
    ) -> MetadataGenerationRunDb:
        """Pull the job state from the Jobs API and finish the run if it terminated.

        ``defer_ingest`` (run id -> None) hands a successful run's ingest to
        the caller instead of running it inline; request handlers use it so a
        slow warehouse read doesn't hold the request.
        """
        if run.status in TERMINAL_RUN_STATUSES:
            return run
        if not run.job_run_id:
            # Committed but the job never launched (e.g. the app stopped in between)
            if run.status == GenerationRunStatus.PENDING.value and self._is_stale(run.created_at):
                run.status = GenerationRunStatus.FAILED.value
                run.error = "The background job was never started"
                run.completed_at = _now()
                db.commit()
            return run
        if not self._jobs:
            return run
        if self._in_ingest_backoff(run):
            return run
        if run.status == GenerationRunStatus.INGESTING.value and not self._is_stale(run.updated_at):
            return run  # the job is done; someone is loading its results
        status = self._jobs.get_job_status(int(run.job_run_id))
        if status is None:
            return self._handle_unavailable_status(db, run, defer_ingest)
        if run.status_unavailable_since is not None:
            run.status_unavailable_since = None
            db.commit()
        if status.get("life_cycle_state") in _TERMINAL_LIFE_CYCLE_STATES:
            # SKIPPED / INTERNAL_ERROR runs have no result state
            result_state = status.get("result_state") or status.get("life_cycle_state")
            if result_state == "SUCCESS" and defer_ingest is not None:
                defer_ingest(run.id)
            else:
                self._finish(db, run, result_state)
        return run

    def _handle_unavailable_status(
        self,
        db: Session,
        run: MetadataGenerationRunDb,
        defer_ingest: Optional[Callable[[str], None]],
    ) -> MetadataGenerationRunDb:
        """The Jobs API didn't report the run's job (unknown/purged run, or an API error)."""
        # Already known to be past job success: its rows are in Delta, so keep ingesting
        if (run.ingest_attempts or 0) > 0 or run.status == GenerationRunStatus.INGESTING.value:
            if defer_ingest is not None:
                defer_ingest(run.id)
            else:
                self.ingest_results(db, run)
            return run
        if run.status_unavailable_since is None:
            run.status_unavailable_since = _now()
            db.commit()
            return run
        if self._is_older_than(run.started_at or run.created_at, JOB_STATUS_GIVE_UP) and self._is_older_than(
            run.status_unavailable_since, JOB_STATUS_UNAVAILABLE_FOR
        ):
            run.status = GenerationRunStatus.FAILED.value
            run.error = "The background job's status is unavailable"
            run.progress_message = None
            run.completed_at = _now()
            db.commit()
        return run

    @staticmethod
    def _is_older_than(timestamp: Optional[datetime], age: timedelta) -> bool:
        if timestamp is None:
            return True
        if timestamp.tzinfo is None:  # SQLite returns naive UTC
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp < _now() - age

    @staticmethod
    def _in_ingest_backoff(run: MetadataGenerationRunDb) -> bool:
        """Whether a failed ingest attempt was too recent to retry yet."""
        attempts = run.ingest_attempts or 0
        if attempts == 0 or run.status != GenerationRunStatus.RUNNING.value or run.updated_at is None:
            return False
        last_failure = run.updated_at
        if last_failure.tzinfo is None:  # SQLite returns naive UTC
            last_failure = last_failure.replace(tzinfo=timezone.utc)
        return _now() < last_failure + INGEST_RETRY_DELAY * (2 ** (attempts - 1))

    @classmethod
    def _is_stale(cls, timestamp: Optional[datetime]) -> bool:
        return cls._is_older_than(timestamp, STALE_INGEST_CLAIM)

    def ingest_run_by_id(self, run_id: str) -> None:
        """Ingest a finished run in its own session (for background tasks)."""
        from src.common.database import get_session_factory

        db = get_session_factory()()
        try:
            run = metagen_runs_repo.get(db, run_id)
            if run is not None:
                self.ingest_results(db, run)
        except Exception:
            logger.error("Background ingest of metadata generation run %s failed", run_id, exc_info=True)
        finally:
            db.close()

    def _refresh_active_runs(
        self, db: Session, *, defer_ingest: Optional[Callable[[str], None]] = None
    ) -> List[MetadataGenerationRunDb]:
        """Finish active runs whose job ended; return the runs still in flight.

        Covers runs nobody has open and whose poller notification was already
        used up, e.g. an ingest claim abandoned by an app restart (taken over
        once stale) or a run whose job never launched. A run whose job
        succeeded and whose ingest was deferred no longer counts as in flight.
        """
        deferred: set = set()

        def defer(run_id: str) -> None:
            deferred.add(run_id)
            defer_ingest(run_id)

        for run in metagen_runs_repo.list_active(db):
            try:
                self.refresh_run(db, run, defer_ingest=defer if defer_ingest else None)
            except Exception:
                logger.warning("Failed to refresh metadata generation run %s", run.id, exc_info=True)
                db.rollback()
        return [r for r in metagen_runs_repo.list_active(db) if r.id not in deferred]

    def handle_job_terminated(self, db: Session, job_run_id: int, result_state: Optional[str]) -> None:
        """JobsManager poller callback for terminated ``metagen_generate`` runs."""
        run = metagen_runs_repo.get_by_job_run_id(db, str(job_run_id))
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return
        if result_state == "SUCCESS":
            self._submit_ingest(run.id)
            return
        self._finish(db, run, result_state)

    def _finish(self, db: Session, run: MetadataGenerationRunDb, result_state: Optional[str]) -> None:
        if result_state == "SUCCESS":
            self.ingest_results(db, run)
            return
        run.status = (
            GenerationRunStatus.CANCELLED.value if result_state == "CANCELED" else GenerationRunStatus.FAILED.value
        )
        if run.status == GenerationRunStatus.FAILED.value:
            run.error = f"Background job ended with {result_state or 'an unknown state'}"
        run.progress_message = None
        run.completed_at = _now()
        db.commit()

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------
    def _claim_for_ingest(self, db: Session, run: MetadataGenerationRunDb) -> bool:
        """Atomically move the run to ``ingesting``; False if someone else holds it.

        The run page's polling and the JobsManager poller can both finish the
        same run from different sessions; only the claimant ingests.
        """
        cutoff = _now() - STALE_INGEST_CLAIM
        claimed = (
            db.query(MetadataGenerationRunDb)
            .filter(
                MetadataGenerationRunDb.id == run.id,
                or_(
                    MetadataGenerationRunDb.status.in_(
                        (GenerationRunStatus.PENDING.value, GenerationRunStatus.RUNNING.value)
                    ),
                    and_(
                        MetadataGenerationRunDb.status == GenerationRunStatus.INGESTING.value,
                        MetadataGenerationRunDb.updated_at < cutoff,
                    ),
                ),
            )
            .update(
                {
                    MetadataGenerationRunDb.status: GenerationRunStatus.INGESTING.value,
                    MetadataGenerationRunDb.progress_message: "Loading generated descriptions",
                    MetadataGenerationRunDb.updated_at: _now(),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        db.refresh(run)
        return claimed == 1

    def ingest_results(self, db: Session, run: MetadataGenerationRunDb) -> int:
        """Load the job's rows from Delta into Description Suggestions.

        Idempotent: a completed run, or one another worker is ingesting, is
        left alone; rows of an interrupted earlier attempt are replaced.
        """
        if (
            run.status == GenerationRunStatus.COMPLETED.value
            or self._in_ingest_backoff(run)
            or not self._claim_for_ingest(db, run)
        ):
            return run.suggestion_count
        try:
            rows = self._fetch_results(run.id, on_page=lambda: self._heartbeat(db, run))
            # A failure while storing rolls back only the half-written suggestions
            with db.begin_nested():
                count = self._store_suggestions(db, run, rows)
            db.commit()
            logger.info("Ingested %d description suggestions for run %s", count, run.id)
            return count
        except Exception as e:
            logger.error("Failed to ingest metadata generation results for run %s: %s", run.id, e, exc_info=True)
            # Drop whatever the failed attempt left in the session (incl. a failed commit)
            db.rollback()
            db.refresh(run)
            run.ingest_attempts = (run.ingest_attempts or 0) + 1
            if run.ingest_attempts < MAX_INGEST_ATTEMPTS:
                # The job succeeded and its rows stay in Delta: the next refresh retries
                run.status = GenerationRunStatus.RUNNING.value
                run.progress_message = "Retrying to load the generated descriptions"
            else:
                run.status = GenerationRunStatus.FAILED.value
                run.error = "Failed to read the generated descriptions"
                run.progress_message = None
                run.completed_at = _now()
            db.commit()
            return 0

    def _store_suggestions(self, db: Session, run: MetadataGenerationRunDb, rows: List[Dict[str, Optional[str]]]) -> int:

        regenerate_existing = bool((run.options or {}).get("regenerate_existing"))
        db.query(DescriptionSuggestionDb).filter(DescriptionSuggestionDb.run_id == run.id).delete()
        # A newer run that already covered an object wins, even if this ingest finishes later
        newer = metagen_suggestions_repo.targets_of_newer_runs(
            db, run=run, table_fqns={row["table_fqn"] for row in rows}
        )

        stored = 0
        targets = []
        for row in rows:
            base_text = (row.get("base_text") or "").strip() or None
            proposed_text = (row.get("proposed_text") or "").strip()
            if not proposed_text:
                continue
            # Fill-gaps-only by default: an existing description is kept
            if base_text and not regenerate_existing:
                continue
            if base_text == proposed_text:
                continue
            column_name = row.get("column_name") or None
            outdated = (row["table_fqn"], column_name) in newer
            db.add(DescriptionSuggestionDb(
                run_id=run.id,
                kind="description",
                object_type=row.get("object_type") or ("column" if column_name else "table"),
                table_fqn=row["table_fqn"],
                column_name=column_name,
                base_text=base_text,
                proposed_text=proposed_text,
                status=SuggestionStatus.SUPERSEDED.value if outdated else SuggestionStatus.PENDING.value,
            ))
            stored += 1
            if not outdated:
                targets.append((row["table_fqn"], column_name))

        # This run replaces older runs' not yet reviewed suggestions for the same objects
        metagen_suggestions_repo.supersede_pending_for_targets(db, run=run, targets=targets)

        run.suggestion_count = stored
        run.status = GenerationRunStatus.COMPLETED.value
        run.progress_message = None
        run.error = None
        run.completed_at = _now()
        db.flush()
        return stored

    def _heartbeat(self, db: Session, run: MetadataGenerationRunDb) -> None:
        """Keep a long ingest's claim (and queued marker) from looking abandoned."""
        db.query(MetadataGenerationRunDb).filter(
            MetadataGenerationRunDb.id == run.id,
            MetadataGenerationRunDb.status == GenerationRunStatus.INGESTING.value,
        ).update({MetadataGenerationRunDb.updated_at: _now()}, synchronize_session=False)
        db.commit()
        with self._queued_lock:
            if run.id in self._queued_ingests:
                self._queued_ingests[run.id] = time.monotonic()

    def _fetch_results(
        self, run_id: str, *, on_page: Optional[Callable[[], None]] = None
    ) -> List[Dict[str, Optional[str]]]:
        """Read this run's rows from the metagen_results Delta table via the SQL warehouse.

        Paged (stable order + LIMIT/OFFSET) so no single response gets near
        the statement API's inline result limit.
        """
        ws = self._ws_factory() if self._ws_factory else None
        if ws is None:
            from src.common.workspace_client import get_workspace_client
            ws = get_workspace_client()

        table = ".".join(f"`{part}`" for part in (*self._output_schema(), RESULTS_TABLE))
        rows: List[Dict[str, Optional[str]]] = []
        while True:
            page = self._fetch_results_page(ws, table, run_id, offset=len(rows))
            rows.extend(page)
            if on_page is not None:
                on_page()
            if len(page) < RESULTS_PAGE_SIZE:
                return rows

    def _fetch_results_page(self, ws: Any, table: str, run_id: str, *, offset: int) -> List[Dict[str, Optional[str]]]:
        from databricks.sdk.service.sql import StatementParameterListItem, StatementState

        resp = ws.statement_execution.execute_statement(
            statement=(
                f"SELECT object_type, table_fqn, column_name, base_text, proposed_text "
                f"FROM {table} WHERE ontos_run_id = :run_id "
                f"ORDER BY table_fqn, column_name NULLS FIRST "
                f"LIMIT {int(RESULTS_PAGE_SIZE)} OFFSET {int(offset)}"
            ),
            warehouse_id=self._settings.DATABRICKS_WAREHOUSE_ID,
            parameters=[StatementParameterListItem(name="run_id", value=run_id)],
            wait_timeout="50s",
        )
        deadline = time.monotonic() + 600
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            if time.monotonic() > deadline:
                raise TimeoutError("Timed out reading metadata generation results")
            time.sleep(2)
            resp = ws.statement_execution.get_statement(resp.statement_id)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            message = resp.status.error.message if resp.status and resp.status.error else "unknown error"
            raise RuntimeError(f"Results query did not succeed: {message}")

        columns = [c.name for c in resp.manifest.schema.columns]
        data = list((resp.result.data_array if resp.result else None) or [])
        for chunk_index in range(1, resp.manifest.total_chunk_count or 1):
            chunk = ws.statement_execution.get_statement_result_chunk_n(resp.statement_id, chunk_index)
            data.extend(chunk.data_array or [])
        return [dict(zip(columns, values)) for values in data]

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_run(self, db: Session, run_id: str) -> Optional[MetadataGenerationRunDb]:
        return metagen_runs_repo.get(db, run_id)

    def list_runs(self, db: Session, user_id: Optional[str], *, limit: int = 50) -> List[MetadataGenerationRunDb]:
        if user_id is None:
            return metagen_runs_repo.list_all(db, limit=limit)
        return metagen_runs_repo.list_for_user(db, user_id, limit=limit)

    def counts(self, db: Session, run_id: str) -> Dict[str, int]:
        return metagen_suggestions_repo.counts_by_status(db, run_id)

    def list_suggestions(
        self, db: Session, run_id: str, *, status: Optional[str] = None, limit: int = 1000, skip: int = 0
    ) -> List[DescriptionSuggestionDb]:
        return metagen_suggestions_repo.list_for_run(db, run_id, status=status, limit=limit, skip=skip)

    def count_suggestions(self, db: Session, run_id: str, *, status: Optional[str] = None) -> int:
        return metagen_suggestions_repo.count_for_run(db, run_id, status=status)
