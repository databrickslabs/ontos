"""TermMappingManager — orchestrates suggestion runs, queue persistence,
apply (which writes through to entity_semantic_links via SemanticLinksManager),
and per-run undo.

Architectural notes:
  * Concept candidates come ONLY from customer ontologies + opted-in shipped
    taxonomies. The internal ``urn:taxonomy:ontos-ontology`` is permanently
    blocked (see concept_source.validate_contexts).
  * One TermMappingManager instance is stored on app.state. Per-request work
    uses a session passed in by the FastAPI dependency wrapper, not a session
    held by the manager itself, so request lifecycles stay clean.
  * Apply uses the existing SemanticLinksManager.add() so all downstream
    side effects (RDF graph update, change_log entry, search index churn)
    keep their familiar code path.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.controller.semantic_links_manager import SemanticLinksManager
from src.db_models.term_mappings import (
    MappingApplyRunDb,
    MappingSuggestionDb,
    RUN_STATUS_APPLIED,
    RUN_STATUS_APPLYING,
    RUN_STATUS_FAILED,
    RUN_STATUS_PENDING,
    RUN_STATUS_SUGGESTED,
    RUN_STATUS_SUGGESTING,
    RUN_STATUS_UNDONE,
    SUG_STATUS_ACCEPTED,
    SUG_STATUS_APPLIED,
    SUG_STATUS_PENDING,
    SUG_STATUS_REJECTED,
)
from src.models.semantic_links import EntitySemanticLinkCreate
from src.models.term_mappings import (
    ApplyResult,
    PendingSuggestionCount,
    RunCreate,
    RunRead,
    RunSummary,
    SuggestionDecision,
    SuggestionDecisionBatch,
    SuggestionDecisionResult,
    SuggestionRead,
    UndoResult,
)
from src.repositories.term_mapping_repository import (
    mapping_run_repo,
    mapping_suggestion_repo,
)

from .term_mapping.adapters import all_adapters
from .term_mapping.concept_source import (
    ConceptSource,
    InvalidContextError,
    resolve_default_customer_contexts,
    validate_contexts,
)
from .term_mapping.engines import HeuristicSuggester
from .term_mapping.engines.heuristic import build_already_decided_fn
from .term_mapping.types import SuggestionDraft, TargetEntity

if TYPE_CHECKING:
    from src.controller.semantic_models_manager import SemanticModelsManager

logger = get_logger(__name__)


class TermMappingManager:
    """Stored once on app.state; per-request methods take a Session arg."""

    def __init__(self, semantic_models_manager: "SemanticModelsManager"):
        self._smm = semantic_models_manager

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------
    def create_run(
        self,
        db: Session,
        *,
        payload: RunCreate,
        created_by: Optional[str],
    ) -> RunRead:
        """Create a run row and immediately execute the configured engines.

        For v1 we run synchronously in the request; on larger workloads this
        moves behind a Databricks job (see PRD Phase 5 follow-up).
        """
        # Default contexts to every enabled customer ontology if omitted.
        contexts = list(payload.ontology_contexts) if payload.ontology_contexts else resolve_default_customer_contexts(self._smm)

        try:
            effective = validate_contexts(contexts, payload.include_shipped)
        except InvalidContextError as e:
            raise ValueError(str(e)) from e

        if not effective:
            raise ValueError(
                "No ontology contexts selected. Upload a customer ontology in "
                "Settings → RDF Sources, or opt into a shipped taxonomy via "
                "include_shipped."
            )

        # Persist the run row in 'pending' state first so we have an id to
        # reference from suggestions and a record even if suggester crashes.
        run = MappingApplyRunDb(
            ontology_contexts=[c for c in effective if c not in payload.include_shipped],
            include_shipped=list(payload.include_shipped),
            target_filter=payload.target_filter.model_dump(exclude_none=True),
            engines=list(payload.engines),
            status=RUN_STATUS_SUGGESTING,
            comment=payload.comment,
            stats={},
            applied_link_ids=[],
            created_by=created_by,
            started_at=_utcnow(),
        )
        db.add(run)
        db.flush()
        run_id = str(run.id)

        # Run the suggester pipeline.
        try:
            targets = list(self._list_targets(db, payload))
            drafts = self._run_engines(db, run, targets, effective)
            self._persist_drafts(db, run, drafts)
            run.stats = _stats_from(targets, drafts)
            run.status = RUN_STATUS_SUGGESTED
            run.finished_at = _utcnow()
            db.commit()
            db.refresh(run)
        except Exception as e:
            logger.exception("Term-mapping run %s failed: %s", run_id, e)
            run.status = RUN_STATUS_FAILED
            run.error = str(e)
            run.finished_at = _utcnow()
            db.commit()
            db.refresh(run)
        return RunRead.model_validate(run)

    def get_run(self, db: Session, run_id: str) -> Optional[RunRead]:
        run = mapping_run_repo.get(db, run_id)
        return RunRead.model_validate(run) if run else None

    def list_runs(self, db: Session, *, limit: int = 50) -> List[RunSummary]:
        rows = mapping_run_repo.list_recent(db, limit=limit)
        return [
            RunSummary(
                id=str(r.id),
                status=r.status,
                comment=r.comment,
                stats=r.stats or {},
                created_by=r.created_by,
                created_at=r.created_at,
                finished_at=r.finished_at,
                applied_at=r.applied_at,
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Suggestion queue
    # ------------------------------------------------------------------
    def list_suggestions(
        self,
        db: Session,
        *,
        run_id: str,
        status: Optional[str] = None,
        source_entity_type: Optional[str] = None,
        source_entity_id: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[SuggestionRead]:
        rows = mapping_suggestion_repo.list_for_run(
            db,
            run_id,
            status=status,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            limit=limit,
            offset=offset,
        )
        return [self._suggestion_to_api(r) for r in rows]

    def list_suggestions_for_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        include_decided: bool = False,
    ) -> List[SuggestionRead]:
        statuses = None if include_decided else (SUG_STATUS_PENDING,)
        rows = mapping_suggestion_repo.list_for_entity(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            statuses=statuses,
        )
        return [self._suggestion_to_api(r) for r in rows]

    def pending_count_for_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
    ) -> PendingSuggestionCount:
        return PendingSuggestionCount(
            entity_type=entity_type,
            entity_id=entity_id,
            pending=mapping_suggestion_repo.count_pending_for_entity(
                db, entity_type=entity_type, entity_id=entity_id
            ),
            auto_apply=mapping_suggestion_repo.count_auto_apply_for_entity(
                db, entity_type=entity_type, entity_id=entity_id
            ),
        )

    def decide(
        self,
        db: Session,
        *,
        batch: SuggestionDecisionBatch,
        decided_by: Optional[str],
    ) -> SuggestionDecisionResult:
        result = SuggestionDecisionResult(accepted=0, rejected=0, skipped=0)
        now = _utcnow()
        for decision in batch.decisions:
            sug = mapping_suggestion_repo.get(db, decision.id)
            if sug is None:
                result.skipped += 1
                result.errors.append(f"suggestion {decision.id} not found")
                continue
            if sug.status not in (SUG_STATUS_PENDING,):
                # Already accepted/rejected/applied/superseded — refuse to
                # mutate so audit history stays meaningful.
                result.skipped += 1
                continue
            if decision.decision == "accept":
                sug.status = SUG_STATUS_ACCEPTED
                if decision.custom_iri:
                    sug.custom_iri = decision.custom_iri
                result.accepted += 1
            else:
                sug.status = SUG_STATUS_REJECTED
                result.rejected += 1
            sug.decided_by = decided_by
            sug.decided_at = now
            db.add(sug)
        db.commit()
        return result

    # ------------------------------------------------------------------
    # Apply / Undo
    # ------------------------------------------------------------------
    def apply_run(
        self,
        db: Session,
        *,
        run_id: str,
        apply_auto: bool = True,
        applied_by: Optional[str],
    ) -> ApplyResult:
        """Write every accepted (and optionally auto_apply pending) suggestion
        in the run as an entity_semantic_links row."""
        run = mapping_run_repo.get(db, run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        run.status = RUN_STATUS_APPLYING
        db.commit()

        # Bootstrap a SemanticLinksManager bound to this session so add()
        # plays nicely with the existing RDF graph / change_log flow.
        sml = SemanticLinksManager(db=db, semantic_models_manager=self._smm)

        result = ApplyResult(run_id=run_id, links_created=0, links_skipped=0)
        try:
            statuses = [SUG_STATUS_ACCEPTED]
            sugs = mapping_suggestion_repo.list_for_run(
                db, run_id, status=None, limit=10_000
            )
            for sug in sugs:
                if sug.status == SUG_STATUS_ACCEPTED:
                    target_iri = sug.custom_iri or sug.target_concept_iri
                elif sug.status == SUG_STATUS_PENDING and apply_auto and sug.auto_apply:
                    target_iri = sug.target_concept_iri
                else:
                    continue

                # Skip engine sentinels (NEW: prefixes etc.) — apply requires a real IRI.
                if not target_iri or target_iri.startswith("NEW:"):
                    result.links_skipped += 1
                    sug.warnings = (sug.warnings or []) + ["orphan_or_new_iri"]
                    db.add(sug)
                    continue

                try:
                    link = sml.add(
                        EntitySemanticLinkCreate(
                            entity_id=sug.source_entity_id,
                            entity_type=sug.source_entity_type,  # type: ignore[arg-type]
                            iri=target_iri,
                            label=sug.target_concept_label,
                        ),
                        created_by=applied_by,
                    )
                except Exception as link_err:
                    logger.warning(
                        "Failed to create link for suggestion %s: %s", sug.id, link_err
                    )
                    result.errors.append(f"{sug.id}: {link_err}")
                    result.links_skipped += 1
                    continue

                sug.status = SUG_STATUS_APPLIED
                try:
                    sug.applied_link_id = _coerce_uuid_or_none(link.id)
                except Exception:
                    sug.applied_link_id = None
                db.add(sug)
                result.links_created += 1
                run.applied_link_ids = (run.applied_link_ids or []) + [str(link.id)]

            run.status = RUN_STATUS_APPLIED
            run.applied_at = _utcnow()
            # Refresh stats with apply numbers
            stats = dict(run.stats or {})
            stats["links_created"] = result.links_created
            stats["links_skipped"] = result.links_skipped
            run.stats = stats
            db.commit()
            db.refresh(run)
        except Exception as e:
            logger.exception("Apply run %s failed: %s", run_id, e)
            run.status = RUN_STATUS_FAILED
            run.error = str(e)
            db.commit()
            raise
        return result

    def undo_run(
        self,
        db: Session,
        *,
        run_id: str,
        undone_by: Optional[str],
    ) -> UndoResult:
        run = mapping_run_repo.get(db, run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        if run.status != RUN_STATUS_APPLIED:
            raise ValueError(
                f"Run {run_id} status is '{run.status}'; can only undo an 'applied' run"
            )

        sml = SemanticLinksManager(db=db, semantic_models_manager=self._smm)
        result = UndoResult(run_id=run_id, links_removed=0, suggestions_reverted=0)

        for link_id in list(run.applied_link_ids or []):
            try:
                removed = sml.remove(link_id, removed_by=undone_by)
                if removed:
                    result.links_removed += 1
                else:
                    result.errors.append(f"link {link_id} already missing")
            except Exception as e:
                logger.warning("Failed to remove link %s during undo: %s", link_id, e)
                result.errors.append(f"link {link_id}: {e}")

        # Walk all applied suggestions and revert them to 'accepted' so the
        # steward can re-trigger apply if undo was a mistake.
        applied_sugs = (
            db.query(MappingSuggestionDb)
            .filter(
                MappingSuggestionDb.run_id == run.id,
                MappingSuggestionDb.status == SUG_STATUS_APPLIED,
            )
            .all()
        )
        for sug in applied_sugs:
            sug.status = SUG_STATUS_ACCEPTED
            sug.applied_link_id = None
            db.add(sug)
            result.suggestions_reverted += 1

        run.status = RUN_STATUS_UNDONE
        run.undone_at = _utcnow()
        run.applied_link_ids = []
        db.commit()
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _list_targets(self, db: Session, payload: RunCreate) -> List[TargetEntity]:
        wanted_types = set(payload.target_filter.entity_types or [])
        targets: List[TargetEntity] = []
        for adapter in all_adapters():
            # Skip adapters that don't serve any of the wanted entity_types.
            if wanted_types and not (set(adapter.entity_types) & wanted_types):
                continue
            targets.extend(adapter.list_targets(db, payload.target_filter))
        return targets

    def _run_engines(
        self,
        db: Session,
        run: MappingApplyRunDb,
        targets: List[TargetEntity],
        contexts: List[str],
    ) -> List[SuggestionDraft]:
        if not targets:
            return []
        source = ConceptSource(self._smm, contexts)
        decided = build_already_decided_fn(db, mapping_suggestion_repo)
        drafts: List[SuggestionDraft] = []
        for engine_name in run.engines or ["heuristic"]:
            if engine_name == "heuristic":
                engine = HeuristicSuggester(concepts=source, already_decided=decided)
                drafts.extend(engine.suggest(targets))
            elif engine_name == "llm_judge":
                # Out of scope for v1; skip silently with a stats marker.
                logger.info("llm_judge engine not yet implemented; skipping")
            else:
                logger.warning("Unknown engine '%s'; skipping", engine_name)
        return drafts

    def _persist_drafts(
        self,
        db: Session,
        run: MappingApplyRunDb,
        drafts: List[SuggestionDraft],
    ) -> None:
        rows = [
            MappingSuggestionDb(
                run_id=run.id,
                source_entity_type=d.source_entity_type,
                source_entity_id=d.source_entity_id,
                source_label=d.source_label,
                suggestion_kind=d.suggestion_kind,
                target_concept_iri=d.target_concept_iri,
                target_concept_label=d.target_concept_label,
                confidence=d.confidence,
                reason=d.reason,
                auto_apply=d.auto_apply,
                engine=d.engine,
                engine_metadata=d.engine_metadata,
                warnings=d.warnings or None,
            )
            for d in drafts
        ]
        mapping_suggestion_repo.bulk_insert(db, rows)

    def _suggestion_to_api(self, row: MappingSuggestionDb) -> SuggestionRead:
        return SuggestionRead(
            id=str(row.id),
            run_id=str(row.run_id),
            source_entity_type=row.source_entity_type,
            source_entity_id=row.source_entity_id,
            source_label=row.source_label,
            suggestion_kind=row.suggestion_kind,  # type: ignore[arg-type]
            target_concept_iri=row.target_concept_iri,
            target_concept_label=row.target_concept_label,
            confidence=row.confidence,
            reason=row.reason,
            auto_apply=row.auto_apply,
            engine=row.engine,  # type: ignore[arg-type]
            engine_metadata=row.engine_metadata,
            status=row.status,  # type: ignore[arg-type]
            decided_by=row.decided_by,
            decided_at=row.decided_at,
            custom_iri=row.custom_iri,
            applied_link_id=str(row.applied_link_id) if row.applied_link_id else None,
            warnings=row.warnings,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


# ---------- module-private helpers ----------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stats_from(targets: List[TargetEntity], drafts: List[SuggestionDraft]) -> Dict[str, Any]:
    auto_apply_count = sum(1 for d in drafts if d.auto_apply)
    return {
        "targets": len(targets),
        "suggestions_total": len(drafts),
        "suggestions_pending": len(drafts),
        "suggestions_accepted": 0,
        "suggestions_rejected": 0,
        "suggestions_auto_apply": auto_apply_count,
        "links_created": 0,
    }


def _coerce_uuid_or_none(value):
    from uuid import UUID
    if value is None:
        return None
    try:
        return UUID(str(value))
    except Exception:
        return None
