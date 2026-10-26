"""
Metadata Generation manager.

A Generation Run runs the ``metagen_generate`` background job (dbxmetagen in
comment mode) over a selection of UC objects. The job writes normalized rows
to the Delta table ``<DATABRICKS_CATALOG>.<DATABRICKS_SCHEMA>.metagen_results``;
when the job finishes, this manager ingests them as Description Suggestions.

Run status is derived from the Jobs API, refreshed on demand by the run page
and by the JobsManager background poller (see ``handle_job_terminated``).
See docs/decisions/metadata-generation-execution.md.

A run's pending suggestions are reviewed in one Data Asset Review (one
ReviewedAsset per suggestion, FQN ``metagen://{run_id}/{suggestion_id}``);
the ``metadata_generation_run`` review workflow handles notifications and
the overall approval. Reviewers' decisions come back through ``decide``.

Once the review is approved, the workflow's ``apply_metadata_suggestions``
step writes the accepted descriptions to UC as the app's service principal
(``apply_review``); "Apply approved" on the run page retries or catches up
(``apply_suggestions``). A target whose UC description changed since
generation is a Conflict and is left alone unless an admin forces it.

Admin settings (``get_feature_settings``, stored in app_settings) cap tables
per run and active runs per user, gate sending sample data and column
statistics to the LLM, and list the serving endpoints runs may use. Ingest
checks which tables the app may change; suggestions for the others are Not
applicable before anyone reviews them.
"""

import json
import threading
import time
import uuid
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from src.common.config import Settings, resolve_volume
from src.common.errors import ConflictError
from src.common.logging import get_logger
from src.common.notification_i18n import notification_i18n_data
from src.db_models.assets import AssetDb
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb
from src.db_models.metadata_generation import DescriptionSuggestionDb, MetadataGenerationRunDb
from src.models.data_asset_reviews import DataAssetReviewRequestCreate, ReviewedAssetStatus, ReviewRequestStatus
from src.models.metadata_generation import (
    TERMINAL_RUN_STATUSES,
    ApplyResult,
    GenerationRunStatus,
    MetadataGenerationSettings,
    MetadataGenerationSettingsResponse,
    StartRunRequest,
    SubmitReviewResponse,
    SuggestionDecisionBatch,
    SuggestionDecisionResult,
    SuggestionStatus,
)
from src.models.notifications import Notification, NotificationType
from src.repositories.app_settings_repository import app_settings_repo
from src.repositories.metadata_generation_repository import (
    metagen_runs_repo,
    metagen_suggestions_repo,
)

logger = get_logger(__name__)

WORKFLOW_ID = "metagen_generate"
# Job parameters start_run passes; the installed job must define all of them
JOB_PARAMETERS = (
    "ontos_run_id", "table_names", "output_catalog", "output_schema", "model", "comment_style",
    "allow_data", "sample_size", "add_metadata", "max_tables", "regenerate_existing",
)
RESULTS_TABLE = "metagen_results"
# Rows per results query; keeps each response well below the 25 MiB inline limit
RESULTS_PAGE_SIZE = 2000
DEFAULT_MODEL = "databricks-claude-sonnet-4-6"
# app_settings key of the admin settings (MetadataGenerationSettings as JSON)
SETTINGS_KEY = "METADATA_GENERATION_SETTINGS"
# Schemas the job skips when expanding a catalog
SKIP_SCHEMAS = {"information_schema"}
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

# Who reviews a run when the submitter names nobody
DEFAULT_REVIEWER_ROLE = "DataSteward"
REVIEW_FQN_PREFIX = "metagen://"
# Suggestions a reviewer can still (re)decide while they're in a review
_DECIDABLE_STATUSES = (
    SuggestionStatus.PENDING.value,
    SuggestionStatus.ACCEPTED.value,
    SuggestionStatus.REJECTED.value,
)
# Review statuses after which its suggestions can't be decided any more
_CLOSED_REVIEW_STATUSES = (
    ReviewRequestStatus.APPROVED.value,
    ReviewRequestStatus.DENIED.value,
    ReviewRequestStatus.CANCELLED.value,
)
FEATURE_ID = "metadata-generation"
# UC SQL errors that mean the app's service principal may not change the object
_PERMISSION_ERRORS = ("PERMISSION_DENIED", "INSUFFICIENT_PERMISSIONS", "does not have MODIFY", "is not the owner")
# Privileges that let a non-owner comment on a table (views need ownership)
_WRITE_PRIVILEGES = {"MODIFY", "ALL_PRIVILEGES"}


class StatementError(RuntimeError):
    """A SQL statement did not succeed."""


def _normalized(text: Optional[str]) -> Optional[str]:
    return (text or "").strip() or None


def _quote_identifier(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _string_literal(text: str) -> str:
    """A Databricks SQL string literal (backslash escapes are on by default)."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


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
        reviews_manager: Any = None,
        notifications_manager: Any = None,
        audit_manager: Any = None,
    ):
        self._settings = settings
        self._audit = audit_manager
        self._jobs = jobs_manager
        self._ws_factory = workspace_client_factory
        self._reviews = reviews_manager
        self._notifications = notifications_manager
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
    # Admin settings
    # ------------------------------------------------------------------
    def get_feature_settings(self, db: Session) -> MetadataGenerationSettings:
        raw = app_settings_repo.get_by_key(db, SETTINGS_KEY)
        if not raw:
            return MetadataGenerationSettings()
        try:
            return MetadataGenerationSettings.model_validate(json.loads(raw))
        except Exception:
            logger.warning("Invalid %s in app settings; using the defaults", SETTINGS_KEY, exc_info=True)
            return MetadataGenerationSettings()

    def update_feature_settings(
        self, db: Session, settings: MetadataGenerationSettings
    ) -> MetadataGenerationSettingsResponse:
        app_settings_repo.set(db, SETTINGS_KEY, settings.model_dump_json())
        return self.settings_response(settings)

    def default_endpoint(self) -> str:
        return self._settings.LLM_ENDPOINT or DEFAULT_MODEL

    def settings_response(self, settings: MetadataGenerationSettings) -> MetadataGenerationSettingsResponse:
        default = self.default_endpoint()
        return MetadataGenerationSettingsResponse(
            **settings.model_dump(),
            default_endpoint=default,
            endpoints=[default] + [e for e in settings.allowed_endpoints if e != default],
        )

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
        settings = self.get_feature_settings(db)
        active = self._refresh_active_runs(db, defer_ingest=defer_ingest)
        limit = settings.max_active_runs_per_user
        if sum(1 for r in active if r.user_id == user_id) >= limit:
            raise ActiveRunLimitError(
                "You already have a Generation Run in progress. Wait for it to finish or cancel it."
                if limit == 1 else
                f"You already have {limit} Generation Runs in progress. Wait for one to finish or cancel it."
            )
        selection = [item.model_dump() for item in request.selection]
        table_names = selection_to_table_names(selection)
        if not self._jobs:
            raise ValueError("Jobs manager not available")

        model = request.model or self.default_endpoint()
        if model not in self.settings_response(settings).endpoints:
            raise ValueError(f"The serving endpoint '{model}' is not allowed for Metadata Generation")
        if request.allow_data and not settings.allow_data_sampling:
            raise ValueError("Sending sample data to the LLM is turned off for Metadata Generation")

        self._check_no_overlapping_run(active, table_names)
        self._check_table_limit(table_names, settings.max_tables_per_run)

        from src.repositories.workflow_installations_repository import workflow_installation_repo
        installation = workflow_installation_repo.get_by_workflow_id(db=db, workflow_id=WORKFLOW_ID)
        if not installation:
            raise ConflictError(
                "The Metadata Generation background job is not enabled. "
                "Ask an administrator to enable it under Settings > Jobs."
            )

        self._check_job_is_current(int(installation.job_id))

        if request.auto_submit and request.reviewer_email and request.reviewer_email.lower() == user_id.lower():
            raise ValueError("You can't review your own Generation Run; pick another reviewer")

        sample_size = settings.sample_size if request.allow_data else 0
        options = {
            "comment_style": request.comment_style.value,
            "model": model,
            "allow_data": request.allow_data,
            "sample_size": sample_size,
            "send_column_metadata": settings.send_column_metadata,
            "regenerate_existing": request.regenerate_existing,
            "auto_submit": request.auto_submit,
            "reviewer_email": request.reviewer_email,
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
            "allow_data": str(request.allow_data).lower(),
            "sample_size": str(sample_size),
            "add_metadata": str(settings.send_column_metadata).lower(),
            "max_tables": str(settings.max_tables_per_run),
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

    def _check_job_is_current(self, job_id: int) -> None:
        """Refuse to launch a job installed from an older definition.

        Installed jobs keep their definition; one without the parameters this
        version passes would reject the run or ignore settings such as the
        column-statistics switch.
        """
        names = self._jobs.get_job_parameter_names(job_id)
        if names is None:
            return
        if set(JOB_PARAMETERS) - names:
            raise ConflictError(
                "The Metadata Generation background job is outdated. Ask an administrator to "
                "turn it off and on again under Settings > Jobs."
            )

    def _check_table_limit(self, table_names: List[str], limit: int) -> None:
        """Reject a selection that covers more than ``limit`` tables.

        Counts what the app's service principal (which the job runs as) can
        list, stopping as soon as the limit is passed. If UC can't be listed
        the job enforces the limit itself.
        """
        try:
            count = self._count_tables(self._workspace(), table_names, stop_after=limit)
        except Exception:
            logger.warning("Failed to count the tables of a Generation Run selection", exc_info=True)
            return
        if count > limit:
            raise ValueError(
                f"The selection covers more than {limit} tables. "
                "Pick fewer schemas or tables, or ask an administrator to raise the limit."
            )

    @staticmethod
    def _count_tables(ws: Any, table_names: List[str], *, stop_after: int) -> int:
        seen: set = set()
        schemas: List[Tuple[str, str]] = []
        for name in table_names:
            parts = name.split(".")
            if len(parts) == 3:
                seen.add(name.lower())
            elif len(parts) == 2:
                schemas.append((parts[0], parts[1]))
            else:
                schemas.extend(
                    (parts[0], schema.name)
                    for schema in ws.schemas.list(catalog_name=parts[0])
                    if schema.name and schema.name.lower() not in SKIP_SCHEMAS
                )
        for catalog, schema in schemas:
            if len(seen) > stop_after:
                break
            # Only these two arguments: the app's CachingWorkspaceClient wraps tables.list
            for table in ws.tables.list(catalog_name=catalog, schema_name=schema):
                seen.add(f"{catalog}.{schema}.{table.name}".lower())
                if len(seen) > stop_after:
                    break
        return len(seen)

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
            unwritable = self._unwritable_tables(
                {row["table_fqn"] for row in rows if row.get("table_fqn")}, on_progress=lambda: self._heartbeat(db, run)
            )
            # A failure while storing rolls back only the half-written suggestions
            with db.begin_nested():
                count = self._store_suggestions(db, run, rows, unwritable=unwritable)
            db.commit()
            logger.info("Ingested %d description suggestions for run %s", count, run.id)
        except Exception as e:
            return self._ingest_failed(db, run, e)
        if (run.options or {}).get("auto_submit") and count:
            self._auto_submit(db, run)
        return count

    def _ingest_failed(self, db: Session, run: MetadataGenerationRunDb, e: Exception) -> int:
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

    def _store_suggestions(
        self,
        db: Session,
        run: MetadataGenerationRunDb,
        rows: List[Dict[str, Optional[str]]],
        *,
        unwritable: Optional[Dict[str, str]] = None,
    ) -> int:
        """Replace the run's suggestions with ``rows``.

        ``unwritable`` (lower-cased table FQN -> reason) marks the suggestions
        of tables the app can't change as Not applicable, so nobody reviews them.
        """
        unwritable = unwritable or {}
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
            blocked = unwritable.get(row["table_fqn"].lower())
            if outdated:
                status = SuggestionStatus.SUPERSEDED.value
            elif blocked:
                status = SuggestionStatus.NOT_APPLICABLE.value
            else:
                status = SuggestionStatus.PENDING.value
            db.add(DescriptionSuggestionDb(
                run_id=run.id,
                kind="description",
                object_type=row.get("object_type") or ("column" if column_name else "table"),
                table_fqn=row["table_fqn"],
                column_name=column_name,
                base_text=base_text,
                proposed_text=proposed_text,
                status=status,
                error=blocked if status == SuggestionStatus.NOT_APPLICABLE.value else None,
            ))
            stored += 1
            if status == SuggestionStatus.PENDING.value:
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

    def _unwritable_tables(
        self, table_fqns: set, *, on_progress: Optional[Callable[[], None]] = None
    ) -> Dict[str, str]:
        """Pre-flight check: the tables the app's service principal can't comment on.

        ``COMMENT ON`` needs ownership of a view, and ownership or ``MODIFY``
        on a table. Returns lower-cased FQN -> reason; a table whose
        permissions can't be read is left out (Apply reports it if it fails).
        """
        if not table_fqns:
            return {}
        try:
            ws = self._workspace()
            me = ws.current_user.me()
            principal = me.user_name
            principals = {principal.lower()} | {
                g.display.lower() for g in (me.groups or []) if getattr(g, "display", None)
            }
        except Exception:
            logger.warning("Failed to identify the app's service principal; skipping the writability check", exc_info=True)
            return {}

        from databricks.sdk.service.catalog import TableType

        unwritable: Dict[str, str] = {}
        for index, fqn in enumerate(sorted(table_fqns)):
            if on_progress is not None and index and index % 50 == 0:
                on_progress()
            try:
                info = ws.tables.get(full_name=fqn)
                if (info.owner or "").lower() in principals:
                    continue
                if info.table_type == TableType.VIEW:
                    unwritable[fqn.lower()] = "The app's service principal must own this view to change its description"
                    continue
                if not self._has_write_privilege(ws, fqn, principal):
                    unwritable[fqn.lower()] = "The app's service principal needs MODIFY on this table to change its description"
            except Exception:
                logger.warning("Failed to check whether the app may change the descriptions of %s", fqn, exc_info=True)
        return unwritable

    @staticmethod
    def _has_write_privilege(ws: Any, fqn: str, principal: str) -> bool:
        page_token = None
        while True:
            resp = ws.grants.get_effective(securable_type="table", full_name=fqn, principal=principal, page_token=page_token)
            for assignment in resp.privilege_assignments or []:
                for p in assignment.privileges or []:
                    privilege = getattr(p.privilege, "value", p.privilege)
                    if privilege in _WRITE_PRIVILEGES:
                        return True
            page_token = getattr(resp, "next_page_token", None)
            if not page_token:
                return False

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
        ws = self._workspace()
        table = ".".join(f"`{part}`" for part in (*self._output_schema(), RESULTS_TABLE))
        rows: List[Dict[str, Optional[str]]] = []
        while True:
            page = self._fetch_results_page(ws, table, run_id, offset=len(rows))
            rows.extend(page)
            if on_page is not None:
                on_page()
            if len(page) < RESULTS_PAGE_SIZE:
                return rows

    def _workspace(self) -> Any:
        """The app's (service principal's) workspace client."""
        ws = self._ws_factory() if self._ws_factory else None
        if ws is None:
            from src.common.workspace_client import get_workspace_client
            ws = get_workspace_client()
        return ws

    def _execute_statement(self, ws: Any, statement: str, parameters: Optional[Dict[str, str]] = None) -> Any:
        """Run a statement on the app's SQL warehouse and wait for it; StatementError unless it succeeded."""
        from databricks.sdk.service.sql import StatementParameterListItem, StatementState

        resp = ws.statement_execution.execute_statement(
            statement=statement,
            warehouse_id=self._settings.DATABRICKS_WAREHOUSE_ID,
            parameters=[StatementParameterListItem(name=k, value=v) for k, v in (parameters or {}).items()] or None,
            wait_timeout="50s",
        )
        deadline = time.monotonic() + 600
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            if time.monotonic() > deadline:
                raise TimeoutError("Timed out waiting for a SQL statement")
            time.sleep(2)
            resp = ws.statement_execution.get_statement(resp.statement_id)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            message = resp.status.error.message if resp.status and resp.status.error else "unknown error"
            raise StatementError(message)
        return resp

    def _fetch_results_page(self, ws: Any, table: str, run_id: str, *, offset: int) -> List[Dict[str, Optional[str]]]:
        try:
            resp = self._execute_statement(
                ws,
                f"SELECT object_type, table_fqn, column_name, base_text, proposed_text "
                f"FROM {table} WHERE ontos_run_id = :run_id "
                f"ORDER BY table_fqn, column_name NULLS FIRST "
                f"LIMIT {int(RESULTS_PAGE_SIZE)} OFFSET {int(offset)}",
                {"run_id": run_id},
            )
        except StatementError as e:
            raise RuntimeError(f"Results query did not succeed: {e}") from e

        columns = [c.name for c in resp.manifest.schema.columns]
        data = list((resp.result.data_array if resp.result else None) or [])
        for chunk_index in range(1, resp.manifest.total_chunk_count or 1):
            chunk = ws.statement_execution.get_statement_result_chunk_n(resp.statement_id, chunk_index)
            data.extend(chunk.data_array or [])
        return [dict(zip(columns, values)) for values in data]

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------
    def create_review_for_run(
        self,
        db: Session,
        run: MetadataGenerationRunDb,
        *,
        requester_email: str,
        reviewer_email: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> SubmitReviewResponse:
        """Put the run's pending suggestions not yet in a review up for review.

        One Data Asset Review per submission, one ReviewedAsset per
        suggestion. The review isn't handed to the generic data asset review
        workflow: the ``metadata_generation_run`` workflow runs instead.
        """
        if self._reviews is None:
            raise ValueError("Asset Review is not available")
        if run.status != GenerationRunStatus.COMPLETED.value:
            raise ValueError("Only a completed Generation Run can be submitted for review")
        candidates = [
            s for s in metagen_suggestions_repo.list_for_run(
                db, run.id, status=SuggestionStatus.PENDING.value, limit=100_000
            )
            if not s.review_request_id
        ]
        if not candidates:
            raise ValueError("No pending suggestions left to review")

        reviewer = reviewer_email or self._default_reviewer(db, requester_email)
        if not reviewer:
            raise ValueError("No Data Steward found to review the run; pick a reviewer")
        if reviewer.lower() == requester_email.lower():
            raise ValueError("You can't review your own Generation Run; pick another reviewer")

        title = f"Descriptions for {self._selection_label(run)}"[:200]
        fqns = [f"{REVIEW_FQN_PREFIX}{run.id}/{s.id}" for s in candidates]
        review = self._reviews.create_review_request(
            DataAssetReviewRequestCreate(
                requester_email=requester_email,
                reviewer_email=reviewer,
                asset_fqns=fqns,
                title=title,
                notes=notes or f"{len(candidates)} generated descriptions from Generation Run {run.id}",
            ),
            db=db,
            trigger_workflow=False,
        )
        asset_ids = {a.asset_fqn: a.id for a in review.assets}
        for fqn, suggestion in zip(fqns, candidates):
            suggestion.review_request_id = review.id
            suggestion.reviewed_asset_id = asset_ids.get(fqn)
        db.commit()

        self._start_review_workflow(
            db, run, review_id=review.id, title=title, requester_email=requester_email,
            reviewer_email=reviewer, suggestion_count=len(candidates),
        )
        self._notify_reviewer(
            db, review_id=review.id, selection=self._selection_label(run), requester_email=requester_email,
            reviewer_email=reviewer, suggestion_count=len(candidates),
        )
        return SubmitReviewResponse(
            run_id=run.id, review_request_id=review.id, reviewer_email=reviewer, suggestion_count=len(candidates),
        )

    def _auto_submit(self, db: Session, run: MetadataGenerationRunDb) -> None:
        """Submit a freshly ingested run for review, as its options ask. Best effort."""
        try:
            self.create_review_for_run(
                db, run, requester_email=run.user_id, reviewer_email=(run.options or {}).get("reviewer_email"),
            )
        except Exception:
            logger.warning("Failed to submit Generation Run %s for review", run.id, exc_info=True)
            db.rollback()

    def _default_reviewer(self, db: Session, requester_email: str) -> Optional[str]:
        from src.common.workflow_executor import resolve_reviewer_email
        return resolve_reviewer_email(db, DEFAULT_REVIEWER_ROLE, requester_email)

    @staticmethod
    def _selection_label(run: MetadataGenerationRunDb) -> str:
        names = [item.get("fqn", "") for item in (run.selection or [])]
        if len(names) <= 2:
            return ", ".join(names)
        return f"{names[0]} and {len(names) - 1} more"

    def _start_review_workflow(
        self,
        db: Session,
        run: MetadataGenerationRunDb,
        *,
        review_id: str,
        title: str,
        requester_email: str,
        reviewer_email: str,
        suggestion_count: int,
    ) -> None:
        """Fire on_request_review for the run (notifications, overall approval). Best effort."""
        try:
            from src.common.workflow_triggers import get_trigger_registry
            from src.models.process_workflows import EntityType

            get_trigger_registry(db).on_request_review(
                entity_type=EntityType.METADATA_GENERATION_RUN,
                entity_id=run.id,
                entity_name=title,
                entity_data={
                    "run_id": run.id,
                    "review_request_id": review_id,
                    "requester_email": requester_email,
                    "reviewer_email": reviewer_email,
                    "suggestion_count": suggestion_count,
                },
                user_email=requester_email,
                blocking=False,
            )
        except Exception:
            logger.error("Failed to start the review workflow for Generation Run %s", run.id, exc_info=True)

    def _notify_reviewer(
        self,
        db: Session,
        *,
        review_id: str,
        selection: str,
        requester_email: str,
        reviewer_email: str,
        suggestion_count: int,
    ) -> None:
        """Point the reviewer at the review (workflow notifications carry no link). Best effort."""
        if self._notifications is None:
            return
        try:
            self._notifications.create_notification(
                Notification(
                    id=str(uuid.uuid4()),
                    recipient=reviewer_email,
                    type=NotificationType.ACTION_REQUIRED,
                    title="Generated descriptions to review",
                    description=(
                        f"{requester_email} asks you to review {suggestion_count} generated descriptions for {selection}."
                    ),
                    link=f"/data-asset-reviews/{review_id}",
                    created_at=_now(),
                    data=notification_i18n_data(
                        "notifications:metadataGeneration.reviewAssigned.title",
                        "notifications:metadataGeneration.reviewAssigned.description",
                        requester=requester_email, count=suggestion_count, selection=selection,
                    ),
                ),
                db,
            )
        except Exception:
            logger.warning("Failed to notify reviewer of review %s", review_id, exc_info=True)

    def get_review_assignees(self, db: Session, review_request_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """(requester, reviewer) emails of a review request, or (None, None)."""
        if not review_request_id:
            return None, None
        review = db.get(DataAssetReviewRequestDb, review_request_id)
        if review is None:
            return None, None
        return review.requester_email, review.reviewer_email

    def decide(
        self,
        db: Session,
        run: MetadataGenerationRunDb,
        batch: SuggestionDecisionBatch,
        *,
        decided_by: str,
        is_admin: bool = False,
    ) -> SuggestionDecisionResult:
        """Record reviewers' decisions on suggestions in a review of ``run``.

        Only the review's reviewer (or a feature admin) decides. Accepted and
        rejected suggestions can be decided again until they are applied or
        the review is closed (approved or rejected as a whole); a
        suggestion sent back for clarification leaves its review and is
        pending again. The ReviewedAsset mirrors each decision.
        """
        result = SuggestionDecisionResult()
        now = _now()
        reviews: Dict[str, Optional[DataAssetReviewRequestDb]] = {}
        for decision in batch.decisions:
            suggestion = db.get(DescriptionSuggestionDb, decision.id)
            if suggestion is None or suggestion.run_id != run.id:
                result.skipped += 1
                result.errors.append(f"Suggestion {decision.id} is not part of this run")
                continue
            if not suggestion.review_request_id or suggestion.status not in _DECIDABLE_STATUSES:
                result.skipped += 1
                result.errors.append(f"Suggestion {decision.id} is not in review")
                continue
            if suggestion.review_request_id not in reviews:
                reviews[suggestion.review_request_id] = db.get(DataAssetReviewRequestDb, suggestion.review_request_id)
            review = reviews[suggestion.review_request_id]
            if review is not None and review.status in _CLOSED_REVIEW_STATUSES:
                result.skipped += 1
                result.errors.append(f"Suggestion {decision.id} is in a closed review")
                continue
            reviewer = review.reviewer_email if review is not None else None
            if not is_admin and (reviewer or "").lower() != decided_by.lower():
                result.skipped += 1
                result.errors.append(f"Suggestion {decision.id} is assigned to another reviewer")
                continue

            comment = (decision.comment or "").strip() or None
            reviewed_asset_id = suggestion.reviewed_asset_id
            if decision.decision == "accept":
                edited = (decision.edited_text or "").strip()
                suggestion.edited_text = edited if edited and edited != suggestion.proposed_text else None
                suggestion.status = SuggestionStatus.ACCEPTED.value
                asset_status = ReviewedAssetStatus.APPROVED
                result.accepted += 1
            elif decision.decision == "reject":
                suggestion.status = SuggestionStatus.REJECTED.value
                asset_status = ReviewedAssetStatus.REJECTED
                result.rejected += 1
            else:
                # Back to pending and out of the review, so it can be submitted again
                suggestion.status = SuggestionStatus.PENDING.value
                suggestion.review_request_id = None
                suggestion.reviewed_asset_id = None
                asset_status = ReviewedAssetStatus.NEEDS_CLARIFICATION
                result.clarify += 1
            suggestion.review_comment = comment
            suggestion.decided_by = decided_by
            suggestion.decided_at = now
            if reviewed_asset_id:
                db.query(ReviewedAssetDb).filter(ReviewedAssetDb.id == reviewed_asset_id).update(
                    {
                        ReviewedAssetDb.status: asset_status.value,
                        ReviewedAssetDb.comments: comment,
                        ReviewedAssetDb.updated_at: now,
                    },
                    synchronize_session=False,
                )
        db.commit()
        return result


    # ------------------------------------------------------------------
    # Close the review / apply to UC
    # ------------------------------------------------------------------
    def close_review(self, db: Session, review_request_id: str, *, approved: bool) -> None:
        """Record the overall outcome of a run's review (workflow approval or rejection).

        Suggestions nobody decided leave the closed review, so they can be
        submitted again. Idempotent: an already closed review keeps its outcome.
        """
        review = db.get(DataAssetReviewRequestDb, review_request_id)
        if review is None:
            return
        if review.status not in _CLOSED_REVIEW_STATUSES:
            review.status = (ReviewRequestStatus.APPROVED if approved else ReviewRequestStatus.DENIED).value
            review.updated_at = _now()
        released = metagen_suggestions_repo.release_undecided(db, review_request_id)
        db.commit()
        logger.info(
            "Review %s of generated descriptions closed (%s); %d undecided suggestions released",
            review_request_id, review.status, released,
        )

    def apply_review(
        self, db: Session, run: MetadataGenerationRunDb, review_request_id: str, *, applied_by: Optional[str],
    ) -> ApplyResult:
        """Workflow step after the reviewer's approval: close the review as approved and apply it."""
        self.close_review(db, review_request_id, approved=True)
        result = self.apply_suggestions(
            db, run, applied_by=applied_by or run.user_id, review_request_id=review_request_id,
        )
        self._audit_apply(applied_by or run.user_id, run, result, source="workflow", force=False)
        return result

    def apply_suggestions(
        self,
        db: Session,
        run: MetadataGenerationRunDb,
        *,
        applied_by: str,
        review_request_id: Optional[str] = None,
        suggestion_ids: Optional[List[str]] = None,
        force: bool = False,
    ) -> ApplyResult:
        """Write the run's accepted suggestions in approved reviews to UC.

        Runs as the app's service principal. Per target, the current UC
        description is read first: if it no longer is the one the suggestion
        was generated against, the suggestion becomes a Conflict and is left
        alone, unless ``force`` (which also retries earlier Conflicts). A
        target that is gone, or that the app may not change, is Not
        applicable; any other failure leaves the suggestion accepted with its
        error, so applying again retries it. Applied text is mirrored into the
        Ontos Asset for the target and recorded in the change log.
        """
        statuses = [SuggestionStatus.ACCEPTED.value]
        if force:
            statuses.append(SuggestionStatus.CONFLICT.value)
        query = metagen_suggestions_repo.applicable_query(
            db, run.id, statuses=statuses, review_request_id=review_request_id,
        )
        if suggestion_ids is not None:
            query = query.filter(DescriptionSuggestionDb.id.in_(suggestion_ids))
        candidates = query.order_by(DescriptionSuggestionDb.table_fqn, DescriptionSuggestionDb.column_name).all()

        result = ApplyResult()
        if not candidates:
            return result
        ws = self._workspace()
        by_table: Dict[str, List[DescriptionSuggestionDb]] = {}
        for suggestion in candidates:
            by_table.setdefault(suggestion.table_fqn, []).append(suggestion)
        for table_fqn, suggestions in by_table.items():
            self._apply_table(db, ws, run, table_fqn, suggestions, result, applied_by=applied_by, force=force)
            db.commit()
        logger.info(
            "Applied descriptions of run %s: %d applied, %d conflicts, %d not applicable, %d failed",
            run.id, result.applied, result.conflict, result.not_applicable, result.failed,
        )
        self._notify_applied(db, run, result)
        return result

    def _apply_table(
        self,
        db: Session,
        ws: Any,
        run: MetadataGenerationRunDb,
        table_fqn: str,
        suggestions: List[DescriptionSuggestionDb],
        result: ApplyResult,
        *,
        applied_by: str,
        force: bool,
    ) -> None:
        from databricks.sdk.errors import NotFound, PermissionDenied

        if table_fqn.count(".") != 2:
            for s in suggestions:
                self._mark(s, SuggestionStatus.NOT_APPLICABLE, result, f"'{table_fqn}' is not a table name")
            return
        try:
            info = ws.tables.get(full_name=table_fqn)
        except NotFound:
            for s in suggestions:
                self._mark(s, SuggestionStatus.NOT_APPLICABLE, result, "The table no longer exists")
            return
        except PermissionDenied:
            for s in suggestions:
                self._mark(s, SuggestionStatus.NOT_APPLICABLE, result, "The app may not read this table")
            return
        except Exception:
            logger.warning("Failed to read the descriptions of %s", table_fqn, exc_info=True)
            for s in suggestions:
                self._mark(s, None, result, "Failed to read the current description")
            return

        column_comments = {(c.name or "").lower(): _normalized(c.comment) for c in (info.columns or [])}
        for s in suggestions:
            if s.column_name and s.column_name.lower() not in column_comments:
                self._mark(s, SuggestionStatus.NOT_APPLICABLE, result, "The column no longer exists")
                continue
            current = column_comments[s.column_name.lower()] if s.column_name else _normalized(info.comment)
            if not force and current != _normalized(s.base_text):
                self._mark(s, SuggestionStatus.CONFLICT, result, "The description in Unity Catalog changed since it was generated")
                continue
            text = (s.edited_text or s.proposed_text).strip()
            if current != text:
                try:
                    self._write_comment(ws, s, text)
                except StatementError as e:
                    if any(marker in str(e) for marker in _PERMISSION_ERRORS):
                        self._mark(s, SuggestionStatus.NOT_APPLICABLE, result, "The app may not change this object's description")
                    else:
                        logger.warning("Failed to write the description of %s: %s", self._target(s), e)
                        self._mark(s, None, result, "Failed to write the description")
                    continue
                except Exception:
                    logger.warning("Failed to write the description of %s", self._target(s), exc_info=True)
                    self._mark(s, None, result, "Failed to write the description")
                    continue
            self._applied(db, run, s, text, before=current, applied_by=applied_by, forced=force and current != _normalized(s.base_text))
            result.applied += 1

    @staticmethod
    def _target(s: DescriptionSuggestionDb) -> str:
        return f"{s.table_fqn}.{s.column_name}" if s.column_name else s.table_fqn

    @staticmethod
    def _mark(
        s: DescriptionSuggestionDb, status: Optional[SuggestionStatus], result: ApplyResult, error: str,
    ) -> None:
        """Record why a suggestion wasn't applied; ``status`` None keeps it as is (retryable)."""
        if status is not None:
            s.status = status.value
        s.error = error
        if status == SuggestionStatus.CONFLICT:
            result.conflict += 1
        elif status == SuggestionStatus.NOT_APPLICABLE:
            result.not_applicable += 1
        else:
            result.failed += 1
            result.errors.append(f"{s.table_fqn}{'.' + s.column_name if s.column_name else ''}: {error}")

    def _write_comment(self, ws: Any, s: DescriptionSuggestionDb, text: str) -> None:
        table = ".".join(_quote_identifier(part) for part in s.table_fqn.split("."))
        if s.column_name:
            statement = f"COMMENT ON COLUMN {table}.{_quote_identifier(s.column_name)} IS {_string_literal(text)}"
        else:
            statement = f"COMMENT ON TABLE {table} IS {_string_literal(text)}"
        self._execute_statement(ws, statement)

    def _applied(
        self,
        db: Session,
        run: MetadataGenerationRunDb,
        s: DescriptionSuggestionDb,
        text: str,
        *,
        before: Optional[str],
        applied_by: str,
        forced: bool,
    ) -> None:
        s.status = SuggestionStatus.APPLIED.value
        s.applied_by = applied_by
        s.applied_at = _now()
        s.applied_text = text
        s.error = None
        # The description is in UC now: record that before the secondary bookkeeping
        db.commit()
        details = {
            "run_id": run.id,
            "suggestion_id": s.id,
            "target": self._target(s),
            "before": before,
            "after": text,
            "approved_by": s.decided_by,
            "applied_by": applied_by,
            "forced": forced,
        }
        from src.controller.change_log_manager import change_log_manager
        try:
            # Assets for UC objects are located by their full name (columns: table.column)
            assets = db.query(AssetDb).filter(func.lower(AssetDb.location) == self._target(s).lower()).all()
            for asset in assets:
                asset.description = text
            db.flush()
            for asset in assets:
                change_log_manager.log_change_with_details(
                    db, entity_type="asset", entity_id=str(asset.id), action="description_applied",
                    username=applied_by, details=details,
                )
            change_log_manager.log_change_with_details(
                db, entity_type="metadata_generation_run", entity_id=run.id, action="description_applied",
                username=applied_by, details=details,
            )
        except Exception:
            # The description is in UC already; the mirror and change log are secondary
            logger.warning("Failed to record the applied description of %s", self._target(s), exc_info=True)
            db.rollback()

    def _audit_apply(self, username: str, run: MetadataGenerationRunDb, result: ApplyResult, *, source: str, force: bool) -> None:
        if self._audit is None:
            return
        self._audit.log_action(
            db=None,
            username=username,
            ip_address=None,
            feature=FEATURE_ID,
            action="APPLY_METADATA_SUGGESTIONS",
            success=result.failed == 0,
            details={
                "run_id": run.id, "source": source, "force": force,
                "applied": result.applied, "conflict": result.conflict,
                "not_applicable": result.not_applicable, "failed": result.failed,
            },
        )

    def _notify_applied(self, db: Session, run: MetadataGenerationRunDb, result: ApplyResult) -> None:
        """Tell the run's owner what was applied. Best effort."""
        if self._notifications is None or not result.total:
            return
        clean = result.conflict == 0 and result.not_applicable == 0 and result.failed == 0
        selection = self._selection_label(run)
        try:
            self._notifications.create_notification(
                Notification(
                    id=str(uuid.uuid4()),
                    recipient=run.user_id,
                    type=NotificationType.SUCCESS if clean else NotificationType.WARNING,
                    title="Generated descriptions applied",
                    description=(
                        f"Written to Unity Catalog for {selection}: {result.applied}. Conflicts: {result.conflict}, "
                        f"not applicable: {result.not_applicable}, failed: {result.failed}."
                    ),
                    link=f"/metadata-generation/runs/{run.id}",
                    created_at=_now(),
                    data=notification_i18n_data(
                        "notifications:metadataGeneration.applied.title",
                        "notifications:metadataGeneration.applied.description",
                        selection=selection, applied=result.applied, conflict=result.conflict,
                        not_applicable=result.not_applicable, failed=result.failed,
                    ),
                ),
                db,
            )
        except Exception:
            logger.warning("Failed to notify the owner of run %s about applied descriptions", run.id, exc_info=True)

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

    def review_summary(self, db: Session, run_id: str) -> Tuple[int, List[str], int]:
        """(pending suggestions not yet submitted, ids of the reviews the run is in, applicable suggestions)."""
        return (
            metagen_suggestions_repo.count_unsubmitted(db, run_id),
            metagen_suggestions_repo.review_request_ids(db, run_id),
            metagen_suggestions_repo.count_applicable(db, run_id),
        )

    def list_suggestions(
        self, db: Session, run_id: str, *, status: Optional[str] = None, limit: int = 1000, skip: int = 0
    ) -> List[DescriptionSuggestionDb]:
        return metagen_suggestions_repo.list_for_run(db, run_id, status=status, limit=limit, skip=skip)

    def get_suggestion(self, db: Session, suggestion_id: str) -> Optional[DescriptionSuggestionDb]:
        return db.get(DescriptionSuggestionDb, suggestion_id)

    def count_suggestions(self, db: Session, run_id: str, *, status: Optional[str] = None) -> int:
        return metagen_suggestions_repo.count_for_run(db, run_id, status=status)
