"""
Model Import Manager (PRD #1718)

Staged, reviewable import of an erwin data model into Ontos:

1. ``create_run`` parses the uploaded file into the IR, stores it on a
   ``model_import_runs`` row and computes a preview. Nothing else is written.
2. ``update_options`` recomputes the preview for new options (scope, target
   collection, contract grouping, catalog mapping, ...).
3. ``confirm_run`` checks the token of the *current* preview and applies the
   run in a background thread: the logical layer becomes concepts in a
   knowledge collection, the physical layer becomes draft data contracts.

Re-imports of the same erwin model (same model id) match earlier output by
erwin object id (``ontos:sourceId`` on concepts), so renames update in place.
Concepts are applied through the semantic-models re-upload path, which
versions modified concepts and deprecates (never deletes) removed ones.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import IO, Any, Callable, Dict, List, Optional, Set

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, SKOS
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.model_import_runs import ModelImportRunDb
from src.model_import.erwin.builder import entities_in
from src.model_import.erwin.ir import ErwinModel
from src.model_import.erwin.map_concepts import ONTOS, ConceptMapping, map_concepts, source_id
from src.model_import.erwin.parse import parse_erwin
from src.model_import.erwin.types import normalize_dbms
from src.models.model_import import ModelImportOptions
from src.models.notifications import Notification, NotificationType, NotificationUpdate
from src.repositories.model_import_runs_repository import model_import_runs_repo

logger = get_logger(__name__)

RUN_TTL = timedelta(days=7)
MAX_CONCURRENT_RUNS_PER_USER = 2
# Preview lists are capped so a 2,000-entity model doesn't produce a 10 MB response.
PREVIEW_LIST_LIMIT = 200


class ModelImportError(ValueError):
    """A user-facing problem with a run (bad state, stale token, ...)."""


class ModelImportConflict(ModelImportError):
    """The run cannot start now (another run of the model is running, cap reached)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def encode_ir(model: ErwinModel) -> bytes:
    return gzip.compress(model.model_dump_json().encode("utf-8"))


def decode_ir(blob: bytes) -> ErwinModel:
    return ErwinModel.model_validate_json(gzip.decompress(blob))


def _token(run_id: str, options: dict, preview: dict) -> str:
    payload = json.dumps({"run": run_id, "options": options, "preview": preview}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


def model_object_ids(model: ErwinModel) -> Set[str]:
    ids = {model.id}
    for e in model.entities:
        ids.add(e.id)
        ids.update(a.id for a in e.attributes)
    ids.update(r.id for r in model.relationships)
    ids.update(d.id for d in model.domains)
    ids.update(s.id for s in model.subject_areas)
    return ids


@dataclass
class ConceptPlan:
    collection_iri: str
    collection_label: str
    collection_exists: bool
    mapping: ConceptMapping
    # The graph to apply: the run's concepts plus everything already in the
    # collection that this run must leave alone.
    merged_graph: Graph
    summary: Dict[str, int]
    new: List[str]
    modified: List[str]
    removed: List[str]


class ModelImportManager:
    """Stages, previews and applies model imports."""

    def __init__(self, semantic_models_manager, data_contracts_manager, notifications_manager=None):
        self._semantic = semantic_models_manager
        self._contracts = data_contracts_manager
        self._notifications = notifications_manager
        self._lock = threading.Lock()
        self._cancel_events: Dict[str, threading.Event] = {}

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_run(self, db: Session, run_id: str) -> Optional[ModelImportRunDb]:
        return model_import_runs_repo.get(db, run_id)

    def list_runs(self, db: Session, user_id: Optional[str], limit: int = 50) -> List[ModelImportRunDb]:
        if model_import_runs_repo.expire_stale(db):
            db.commit()
        return model_import_runs_repo.list(db, user_id=user_id, limit=limit)

    def load_model(self, run: ModelImportRunDb) -> ErwinModel:
        if not run.model_ir:
            raise ModelImportError("This run no longer holds its model (expired). Upload the file again.")
        return decode_ir(run.model_ir)

    # ------------------------------------------------------------------
    # Create / update / confirm
    # ------------------------------------------------------------------

    def create_run(
        self,
        db: Session,
        *,
        stream: IO[bytes],
        filename: Optional[str],
        size_bytes: int,
        sha256: str,
        user_id: str,
        options: Optional[ModelImportOptions] = None,
    ) -> ModelImportRunDb:
        """Parse an uploaded export and stage a run with its preview.

        Raises ``ErwinParseError`` (a ValueError) for files that are not erwin exports.
        """
        model = parse_erwin(stream)
        opts = self._default_options(db, model, options)
        run = ModelImportRunDb(
            user_id=user_id,
            status="previewed",
            source_kind="file_xml",
            source_filename=filename,
            source_sha256=sha256,
            source_size_bytes=size_bytes,
            source_model_id=model.id,
            source_model_name=model.name,
            source_model_version=model.version,
            model_ir=encode_ir(model),
            expires_at=_now() + RUN_TTL,
        )
        model_import_runs_repo.add(db, run)
        self._refresh_preview(db, run, model, opts)
        db.commit()
        db.refresh(run)
        return run

    def update_options(self, db: Session, run: ModelImportRunDb, options: ModelImportOptions) -> ModelImportRunDb:
        if run.status != "previewed":
            raise ModelImportError(f"Run is {run.status}; only a previewed run can change its options.")
        model = self.load_model(run)
        self._refresh_preview(db, run, model, self._default_options(db, model, options))
        run.expires_at = _now() + RUN_TTL
        db.commit()
        db.refresh(run)
        return run

    def confirm_run(
        self, db: Session, run: ModelImportRunDb, token: str, actor: str,
        *, run_inline: bool = False,
    ) -> ModelImportRunDb:
        """Apply a previewed run. ``run_inline`` executes synchronously (tests, small runs)."""
        if run.status != "previewed":
            raise ModelImportError(f"Run is {run.status}; it can no longer be confirmed.")
        if run.expires_at and run.expires_at.replace(tzinfo=run.expires_at.tzinfo or timezone.utc) < _now():
            raise ModelImportError("Run has expired. Upload the file again.")
        if not token or token != run.confirm_token:
            raise ModelImportError("The preview changed since it was shown. Review the new preview and confirm again.")
        if model_import_runs_repo.running_for_model(db, run.source_model_id):
            raise ModelImportConflict("Another import of this model is running. Wait for it to finish.")
        if model_import_runs_repo.count_running_for_user(db, run.user_id) >= MAX_CONCURRENT_RUNS_PER_USER:
            raise ModelImportConflict(
                f"Concurrent import limit reached ({MAX_CONCURRENT_RUNS_PER_USER}). Wait for a running import to finish."
            )
        run.status = "running"
        run.progress_message = "Starting import…"
        run.confirm_token = None
        run.notification_id = self._create_notification(db, run)
        db.commit()

        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[run.id] = cancel_event
        if run_inline:
            self._execute(run.id, actor, cancel_event, session_factory=lambda: db, close_session=False)
            db.refresh(run)
            return run
        threading.Thread(
            target=self._execute, args=(run.id, actor, cancel_event), daemon=True,
        ).start()
        return run

    def cancel_run(self, db: Session, run: ModelImportRunDb) -> ModelImportRunDb:
        if run.status == "previewed":
            run.status = "cancelled"
            run.model_ir = None
            run.confirm_token = None
            run.completed_at = _now()
            db.commit()
            return run
        if run.status == "running":
            with self._lock:
                event = self._cancel_events.get(run.id)
            if event:
                event.set()
            return run
        raise ModelImportError(f"Run is {run.status}; nothing to cancel.")

    # ------------------------------------------------------------------
    # Options & preview
    # ------------------------------------------------------------------

    def _default_options(
        self, db: Session, model: ErwinModel, options: Optional[ModelImportOptions],
    ) -> ModelImportOptions:
        """Fill unset options from the previous completed import of the same model."""
        opts = options.model_copy(deep=True) if options else ModelImportOptions()
        previous = model_import_runs_repo.latest_completed_for_model(db, model.id)
        if previous and previous.options:
            prev = ModelImportOptions.model_validate(previous.options)
            fields_set = options.model_fields_set if options else set()
            for name in ("collection_iri", "contract_grouping", "catalog_mappings", "table_overrides",
                         "dbms", "migration_mode", "udp_mappings", "domain_by_group"):
                if name not in fields_set:
                    setattr(opts, name, getattr(prev, name))
        if opts.collection_iri is None and opts.import_logical:
            opts.collection_iri = self._collection_iri_for(model.name)
        known_sa = {s.id for s in model.subject_areas}
        opts.subject_area_ids = [s for s in opts.subject_area_ids if s in known_sa]
        return opts

    @staticmethod
    def _collection_iri_for(label: str) -> str:
        # Same IRI create_collection mints for an "ontology" collection.
        from src.controller.semantic_models_manager import _sanitize_context_name
        return f"urn:ontology:{_sanitize_context_name(label.lower().replace(' ', '-'))}"

    def _refresh_preview(
        self, db: Session, run: ModelImportRunDb, model: ErwinModel, options: ModelImportOptions,
    ) -> None:
        preview = self.build_preview(db, model, options, run_id=run.id)
        opts = options.model_dump(mode="json")
        run.options = opts
        run.preview = preview
        run.confirm_token = _token(run.id, opts, preview)

    def build_preview(
        self, db: Session, model: ErwinModel, options: ModelImportOptions, run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        scope = entities_in(model, options.subject_area_ids)
        previous = model_import_runs_repo.latest_completed_for_model(db, model.id, exclude_run_id=run_id)
        preview: Dict[str, Any] = {
            "model": {
                "id": model.id,
                "name": model.name,
                "model_type": model.model_type.value,
                "target_dbms": model.target_dbms,
                "dbms": options.dbms or normalize_dbms(model.target_dbms),
                "version": model.version,
                "entities": sum(1 for e in model.entities if not e.is_view),
                "views": sum(1 for e in model.entities if e.is_view),
                "attributes": sum(len(e.attributes) for e in model.entities),
                "relationships": len(model.relationships),
                "domains": sum(1 for d in model.domains if not d.is_builtin),
                "udps": model.udp_names,
                "subject_areas": [
                    {"id": s.id, "name": s.name, "entities": len(s.entity_ids)} for s in model.subject_areas
                ],
            },
            "scope": {"entities": len(scope), "subject_area_ids": options.subject_area_ids},
            "previous_run_id": previous.id if previous else None,
            "warnings": list(model.warnings),
            "logical": None,
            "physical": None,
        }
        if options.import_logical and options.collection_iri:
            plan = self.plan_concepts(db, model, options)
            preview["logical"] = {
                "collection_iri": plan.collection_iri,
                "collection_label": plan.collection_label,
                "collection_exists": plan.collection_exists,
                "counts": plan.mapping.counts,
                "summary": plan.summary,
                "new": self._labels(plan.merged_graph, plan.new),
                "modified": self._labels(plan.merged_graph, plan.modified),
                "removed": self._labels(self._current_graph(db, plan.collection_iri), plan.removed),
            }
        return preview

    @staticmethod
    def _labels(graph: Graph, iris: List[str]) -> List[Dict[str, str]]:
        out = []
        for iri in iris[:PREVIEW_LIST_LIMIT]:
            label = graph.value(URIRef(iri), SKOS.prefLabel)
            out.append({"iri": iri, "label": str(label) if label is not None else iri})
        return out

    # ------------------------------------------------------------------
    # Logical layer → concepts
    # ------------------------------------------------------------------

    def _current_rows(self, db: Session, collection_iri: str):
        from src.repositories.rdf_triples_repository import rdf_triples_repo
        return rdf_triples_repo.list_current_by_context(db, collection_iri)

    def _current_graph(self, db: Session, collection_iri: str) -> Graph:
        from src.controller.concept_diff import _rebuild_current_graph
        return _rebuild_current_graph(self._current_rows(db, collection_iri))

    def plan_concepts(self, db: Session, model: ErwinModel, options: ModelImportOptions,
                      source_filename: Optional[str] = None) -> ConceptPlan:
        from src.controller.concept_diff import _rebuild_current_graph, compute_concept_diff

        collection_iri = options.collection_iri
        collection = self._semantic.get_collection(collection_iri)
        label = (collection or {}).get("label") or model.name
        rows = self._current_rows(db, collection_iri) if collection else []
        current = _rebuild_current_graph(rows)

        existing_iris: Dict[str, str] = {}
        for s, o in current.subject_objects(ONTOS.sourceId):
            existing_iris[str(o)] = str(s)

        scope_ids = [e.id for e in entities_in(model, options.subject_area_ids)]
        mapping = map_concepts(model, collection_iri, scope_ids, existing_iris)
        incoming = mapping.graph
        # Governance stamps for concepts this run creates (ignored by the diff).
        for s in set(incoming.subjects(RDF.type, OWL.Class)) | set(incoming.subjects(RDF.type, SKOS.Concept)):
            incoming.add((s, ONTOS.status, Literal("draft")))
            if source_filename:
                incoming.set((s, ONTOS.sourceFile, Literal(source_filename)))

        merged = Graph()
        for t in incoming:
            merged.add(t)
        incoming_subjects = set(incoming.subjects())
        prefix = source_id(model, "")
        alive = model_object_ids(model)
        for s in set(current.subjects()):
            if s in incoming_subjects:
                continue
            sid = current.value(s, ONTOS.sourceId)
            if sid is not None and str(sid).startswith(prefix) and str(sid)[len(prefix):] not in alive:
                # Gone from the model → left out, so the diff deprecates it.
                continue
            # Not produced by this run (outside the chosen subject areas, or
            # not from this model at all): keep as is.
            for p, o in current.predicate_objects(s):
                merged.add((s, p, o))

        diff = compute_concept_diff(merged, rows)
        return ConceptPlan(
            collection_iri=collection_iri,
            collection_label=label,
            collection_exists=collection is not None,
            mapping=mapping,
            merged_graph=merged,
            summary=diff.summary(),
            new=diff.new,
            modified=diff.modified,
            removed=diff.removed,
        )

    def _apply_concepts(self, db: Session, model: ErwinModel, options: ModelImportOptions,
                        run: ModelImportRunDb, actor: str) -> Dict[str, Any]:
        if not self._semantic.get_collection(options.collection_iri):
            created = self._semantic.create_collection(
                label=model.name,
                collection_type="ontology",
                description=f"Imported from erwin model '{model.name}'.",
                created_by=actor,
            )
            if created["iri"] != options.collection_iri:
                raise ModelImportError(
                    f"Collection IRI mismatch: expected {options.collection_iri}, created {created['iri']}."
                )
        plan = self.plan_concepts(db, model, options, source_filename=run.source_filename)
        summary = self._semantic.apply_upload_as_versioning_event(
            plan.collection_iri, plan.merged_graph, actor=actor, conflict_mode="block",
        )
        return {
            "collection_iri": plan.collection_iri,
            "summary": summary,
            "counts": plan.mapping.counts,
            "iri_by_id": plan.mapping.iri_by_id,
        }

    # ------------------------------------------------------------------
    # Physical layer → contracts (slice 3)
    # ------------------------------------------------------------------

    def _apply_contracts(self, db: Session, model: ErwinModel, options: ModelImportOptions,
                         run: ModelImportRunDb, actor: str, iri_by_id: Dict[str, str],
                         progress: Callable[[str], None], cancel_event: threading.Event) -> Dict[str, Any]:
        return {"contracts": []}

    # ------------------------------------------------------------------
    # Background execution
    # ------------------------------------------------------------------

    def _execute(self, run_id: str, actor: str, cancel_event: threading.Event,
                 session_factory: Optional[Callable[[], Session]] = None,
                 close_session: bool = True) -> None:
        if session_factory is None:
            from src.common.database import get_session_factory
            session_factory = get_session_factory()
        db = session_factory()
        run = None
        try:
            run = model_import_runs_repo.get(db, run_id)
            model = self.load_model(run)
            options = ModelImportOptions.model_validate(run.options or {})
            result: Dict[str, Any] = {"logical": None, "physical": None, "warnings": list(model.warnings)}

            def progress(message: str) -> None:
                run.progress_message = message
                db.commit()
                self._update_notification(db, run, message)

            iri_by_id: Dict[str, str] = {}
            if options.import_logical and options.collection_iri:
                progress("Importing concepts…")
                logical = self._apply_concepts(db, model, options, run, actor)
                iri_by_id = logical.pop("iri_by_id")
                result["logical"] = logical
            if cancel_event.is_set():
                self._finish(db, run, "cancelled", result, "Cancelled after the concepts were imported.")
                return
            if options.import_physical:
                progress("Importing contracts…")
                result["physical"] = self._apply_contracts(
                    db, model, options, run, actor, iri_by_id, progress, cancel_event,
                )
            status = "cancelled" if cancel_event.is_set() else "completed"
            self._finish(db, run, status, result, "Import complete." if status == "completed" else "Cancelled.")
        except Exception as exc:
            logger.exception("Model import run %s failed", run_id)
            try:
                db.rollback()
                run = model_import_runs_repo.get(db, run_id)
                if run is not None:
                    self._finish(db, run, "failed", run.result, None, error=str(exc))
            except Exception:
                logger.exception("Could not record failure of model import run %s", run_id)
                db.rollback()
        finally:
            with self._lock:
                self._cancel_events.pop(run_id, None)
            if close_session:
                db.close()

    def _finish(self, db: Session, run: ModelImportRunDb, status: str, result: Optional[Dict[str, Any]],
                message: Optional[str], error: Optional[str] = None) -> None:
        run.status = status
        run.result = result
        run.progress_message = message
        run.error = error
        run.completed_at = _now()
        db.commit()
        self._finalize_notification(db, run)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _create_notification(self, db: Session, run: ModelImportRunDb) -> Optional[str]:
        if not self._notifications:
            return None
        try:
            n = Notification(
                id=f"model-import-{run.id}",
                type=NotificationType.JOB_PROGRESS,
                title="Model import running",
                subtitle=run.source_model_name or "erwin model",
                message="Importing the model in the background…",
                link=f"/model-imports/{run.id}",
                recipient=run.user_id,
                data={"run_id": run.id, "progress": 0, "status": "running"},
                created_at=_now(),
            )
            self._notifications.create_notification(n, db=db)
            return n.id
        except Exception as exc:
            logger.warning("Could not create model-import notification: %s", exc)
            return None

    def _update_notification(self, db: Session, run: ModelImportRunDb, message: str) -> None:
        if not (self._notifications and run.notification_id):
            return
        try:
            self._notifications.update_notification(
                run.notification_id,
                NotificationUpdate(message=message, data={"run_id": run.id, "status": "running"},
                                   updated_at=_now()),
                db=db,
            )
            db.commit()
        except Exception as exc:
            logger.debug("Model-import notification update failed: %s", exc)
            db.rollback()

    def _finalize_notification(self, db: Session, run: ModelImportRunDb) -> None:
        if not (self._notifications and run.notification_id):
            return
        titles = {"completed": "Model import complete", "cancelled": "Model import cancelled",
                  "failed": "Model import failed"}
        try:
            self._notifications.update_notification(
                run.notification_id,
                NotificationUpdate(
                    title=titles.get(run.status, "Model import"),
                    message=run.error or run.progress_message or "",
                    data={"run_id": run.id, "progress": 100, "status": run.status},
                    updated_at=_now(),
                ),
                db=db,
            )
            db.commit()
        except Exception as exc:
            logger.debug("Model-import notification finalize failed: %s", exc)
            db.rollback()
