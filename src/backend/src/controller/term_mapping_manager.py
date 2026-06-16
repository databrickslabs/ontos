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
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.controller.semantic_links_manager import SemanticLinksManager
from src.models.notifications import Notification, NotificationType
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
    SUG_STATUS_NEEDS_CLARIFICATION,
    SUG_STATUS_PENDING,
    SUG_STATUS_REJECTED,
)
from src.models.data_asset_reviews import (
    DataAssetReviewRequestCreate,
    ReviewedAssetStatus,
)
from src.models.semantic_links import EntitySemanticLinkCreate
from src.models.term_mappings import (
    ApplyResult,
    GenerateReviewRequest,
    GenerateReviewResponse,
    InlineSuggestRequest,
    InlineSuggestResponse,
    InlineSuggestion,
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
    INTERNAL_BLOCKED_CONTEXTS,
    ConceptSource,
    InvalidContextError,
    resolve_default_customer_contexts,
    resolve_inline_default_contexts,
    validate_contexts,
)
from .term_mapping.engines import HeuristicSuggester
from .term_mapping.engines.heuristic import build_already_decided_fn
from .term_mapping.types import SuggestionDraft, TargetEntity

if TYPE_CHECKING:
    from src.controller.data_asset_reviews_manager import DataAssetReviewManager
    from src.controller.notifications_manager import NotificationsManager
    from src.controller.semantic_models_manager import SemanticModelsManager

logger = get_logger(__name__)


class TermMappingManager:
    """Stored once on app.state; per-request methods take a Session arg.

    `reviews_manager` is optional at construction so the unit tests stay
    cheap; the production startup wiring always injects it. When absent,
    ``create_review_for_run`` raises and the per-row AR forward-sync becomes
    a no-op so direct workbench decisions still work.
    """

    def __init__(
        self,
        semantic_models_manager: "SemanticModelsManager",
        reviews_manager: Optional["DataAssetReviewManager"] = None,
        notifications_manager: Optional["NotificationsManager"] = None,
    ):
        self._smm = semantic_models_manager
        self._reviews_manager = reviews_manager
        self._notifications_manager = notifications_manager

    def set_reviews_manager(self, reviews_manager: "DataAssetReviewManager") -> None:
        """Late-binding hook so startup can wire the AR manager after both
        singletons are constructed (avoids construction order coupling)."""
        self._reviews_manager = reviews_manager

    def set_notifications_manager(self, notifications_manager: "NotificationsManager") -> None:
        """Late-binding hook for the notifications manager, mirroring
        ``set_reviews_manager``. Kept optional so unit tests can construct a
        manager without wiring the full notifications stack."""
        self._notifications_manager = notifications_manager

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
        """Apply steward decisions to one or more suggestions.

        On `accept`: mark accepted **and** immediately write the
        entity_semantic_links row (per-row apply). This matches the MDM
        flow where Approve = the merged record is created right there in
        the editor. The row's status becomes ``applied`` if the link
        succeeds (``accepted`` if it fails, with the error captured in
        ``warnings`` so the next bulk Apply picks it up again).

        On `reject` / `clarify`: just flip the status. Forward-sync the
        linked ReviewedAsset row so the AR UI reflects the same decision.
        """
        result = SuggestionDecisionResult(accepted=0, rejected=0, skipped=0)
        now = _utcnow()
        affected_run_ids: set = set()
        # Lazy SemanticLinksManager construction — only if we have at
        # least one accept that actually fires.
        sml: Optional[SemanticLinksManager] = None

        for decision in batch.decisions:
            sug = mapping_suggestion_repo.get(db, decision.id)
            if sug is None:
                result.skipped += 1
                result.errors.append(f"suggestion {decision.id} not found")
                continue
            if sug.status not in (SUG_STATUS_PENDING,):
                result.skipped += 1
                continue

            sug.decided_by = decided_by
            sug.decided_at = now
            affected_run_ids.add(sug.run_id)

            ar_status: Optional[ReviewedAssetStatus] = None

            if decision.decision == "accept":
                sug.status = SUG_STATUS_ACCEPTED
                if decision.custom_iri:
                    sug.custom_iri = decision.custom_iri
                result.accepted += 1

                # Per-row apply: write the link now. If anything explodes
                # we keep the status at ACCEPTED so the next Apply Run
                # call sweeps it up.
                if sml is None:
                    sml = SemanticLinksManager(db=db, semantic_models_manager=self._smm)
                target_iri = sug.custom_iri or sug.target_concept_iri
                if not target_iri or target_iri.startswith("NEW:"):
                    sug.warnings = (sug.warnings or []) + ["orphan_or_new_iri"]
                else:
                    try:
                        link = sml.add(
                            EntitySemanticLinkCreate(
                                entity_id=sug.source_entity_id,
                                entity_type=sug.source_entity_type,  # type: ignore[arg-type]
                                iri=target_iri,
                                label=sug.target_concept_label,
                            ),
                            created_by=decided_by,
                        )
                        sug.status = SUG_STATUS_APPLIED
                        try:
                            sug.applied_link_id = _coerce_uuid_or_none(link.id)
                        except Exception:
                            sug.applied_link_id = None
                        # Track the link id on the run so the existing
                        # undo can sweep it up.
                        run = mapping_run_repo.get(db, sug.run_id)
                        if run is not None:
                            run.applied_link_ids = (run.applied_link_ids or []) + [str(link.id)]
                            db.add(run)
                    except Exception as link_err:
                        logger.warning(
                            "Per-row apply failed for suggestion %s: %s", sug.id, link_err
                        )
                        sug.warnings = (sug.warnings or []) + [f"apply_failed:{link_err}"]
                        result.errors.append(f"{sug.id}: {link_err}")

                ar_status = ReviewedAssetStatus.APPROVED
            elif decision.decision == "reject":
                sug.status = SUG_STATUS_REJECTED
                result.rejected += 1
                ar_status = ReviewedAssetStatus.REJECTED
            elif decision.decision == "clarify":
                sug.status = SUG_STATUS_NEEDS_CLARIFICATION
                # We don't have a "clarified" counter, so don't bump
                # accepted/rejected; UI surfaces the per-status list.
                result.skipped += 1
                ar_status = ReviewedAssetStatus.NEEDS_CLARIFICATION
            else:
                # Defensive: should be caught by Pydantic Literal already.
                result.skipped += 1
                result.errors.append(f"unknown decision '{decision.decision}'")
                continue

            db.add(sug)

            # Forward-sync the linked ReviewedAsset (MDM pattern). Best
            # effort: a failure here doesn't roll back the decision.
            if ar_status is not None and sug.reviewed_asset_id and self._reviews_manager:
                try:
                    self._reviews_manager.update_asset_status_by_id(
                        str(sug.reviewed_asset_id), ar_status, db=db
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to sync ReviewedAsset %s for suggestion %s: %s",
                        sug.reviewed_asset_id, sug.id, e,
                    )

        for run_id in affected_run_ids:
            self._refresh_run_stats(db, run_id)
        db.commit()
        return result

    def _refresh_run_stats(self, db: Session, run_id) -> None:
        """Recompute the cached pending/accepted/rejected counters on a run.

        We keep the snapshotted `targets`, `suggestions_total`,
        `suggestions_auto_apply` and `links_created`/`links_skipped` so the
        history (e.g. how many candidates the suggester originally produced)
        survives later decisions.
        """
        run = mapping_run_repo.get(db, run_id)
        if run is None:
            return
        stats = dict(run.stats or {})
        sugs = mapping_suggestion_repo.list_for_run(db, run_id, status=None, limit=100_000)
        by_status: Dict[str, int] = {}
        for s in sugs:
            by_status[s.status] = by_status.get(s.status, 0) + 1
        stats["suggestions_pending"] = by_status.get(SUG_STATUS_PENDING, 0)
        stats["suggestions_accepted"] = by_status.get(SUG_STATUS_ACCEPTED, 0)
        stats["suggestions_rejected"] = by_status.get(SUG_STATUS_REJECTED, 0)
        stats["suggestions_applied"] = by_status.get(SUG_STATUS_APPLIED, 0)
        # Auto-apply counter only counts *pending* candidates — once decided
        # they live in accepted/rejected and lose their "would auto-apply"
        # meaning. Recompute from the live pending set.
        stats["suggestions_auto_apply"] = sum(
            1 for s in sugs if s.status == SUG_STATUS_PENDING and s.auto_apply
        )
        run.stats = stats
        db.add(run)

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
            # _refresh_run_stats recomputes pending/accepted/applied counters
            # from the live suggestions table, then we overlay the apply-side
            # numbers (created/skipped) which are not derivable from status.
            self._refresh_run_stats(db, run_id)
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
        self._refresh_run_stats(db, run.id)
        # links_created/skipped from the prior apply are no longer accurate
        # after an undo — zero them out so the UI doesn't keep boasting old
        # numbers next to a "undone" status.
        stats = dict(run.stats or {})
        stats["links_created"] = 0
        stats["links_skipped"] = 0
        run.stats = stats
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
            review_request_id=str(row.review_request_id) if row.review_request_id else None,
            reviewed_asset_id=str(row.reviewed_asset_id) if row.reviewed_asset_id else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # ------------------------------------------------------------------
    # Review spawn (MDM-style write-through copy)
    # ------------------------------------------------------------------
    def create_review_for_run(
        self,
        db: Session,
        *,
        run_id: str,
        payload: GenerateReviewRequest,
        requester_email: Optional[str],
    ) -> GenerateReviewResponse:
        """Spawn a DataAssetReviewRequest holding all pending (and optionally
        accepted) suggestions for the run, exactly the way MdmManager does."""
        if not self._reviews_manager:
            raise ValueError("Reviews manager not configured")
        run = mapping_run_repo.get(db, run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        statuses_to_include = [SUG_STATUS_PENDING]
        if payload.include_accepted:
            statuses_to_include.append(SUG_STATUS_ACCEPTED)
        candidates = [
            s for s in mapping_suggestion_repo.list_for_run(db, run_id, status=None, limit=100_000)
            if s.status in statuses_to_include and not s.review_request_id
        ]
        if not candidates:
            raise ValueError("No suggestions eligible for review (already in a review or no pending rows)")

        # Asset FQN per MDM convention: term-mapping://{run_id}/{suggestion_id}
        asset_fqns = [f"term-mapping://{run_id}/{s.id}" for s in candidates]

        effective_requester = payload.requester_email or requester_email
        if not effective_requester:
            raise ValueError("requester_email could not be resolved (no caller email available)")

        review_data = DataAssetReviewRequestCreate(
            requester_email=effective_requester,
            reviewer_email=payload.reviewer_email,
            asset_fqns=asset_fqns,
            notes=payload.notes
            or f"Term-mapping review for run {run_id} — {len(candidates)} suggestions",
        )
        review = self._reviews_manager.create_review_request(
            request_data=review_data, db=db
        )

        # Wire suggestion ↔ ReviewedAsset back-pointers in source order.
        # create_review_request preserves order when constructing assets.
        for i, sug in enumerate(candidates):
            if i < len(review.assets):
                sug.review_request_id = _coerce_uuid_or_none(review.id)
                sug.reviewed_asset_id = _coerce_uuid_or_none(review.assets[i].id)
                db.add(sug)
        db.commit()

        # Reviewer notification is fired by DataAssetReviewsManager itself
        # (workflow trigger with direct-notification fallback). What's missing
        # there is a confirmation back to the steward who spawned the review
        # so they can track it from notifications without polling the runs
        # list. Notifications manager is optional in unit-test contexts so we
        # guard the call; failure here must not block review creation.
        self._notify_review_spawned(
            run_id=str(run.id),
            review_id=review.id,
            suggestion_count=len(candidates),
            requester_email=effective_requester,
            reviewer_email=payload.reviewer_email,
        )

        return GenerateReviewResponse(
            run_id=str(run.id),
            review_request_id=review.id,
            suggestion_count=len(candidates),
            message=f"Created review request with {len(candidates)} suggestions",
        )

    def _notify_review_spawned(
        self,
        *,
        run_id: str,
        review_id: str,
        suggestion_count: int,
        requester_email: str,
        reviewer_email: str,
    ) -> None:
        """Confirmation ping to the steward who triggered the AR spawn.

        Mirrors the pattern AR uses for its reviewer notification but is
        scoped to the requester so they see the review they just created in
        their own notifications feed. Best-effort: a failed notification
        must not break the spawn path (AR is already persisted)."""
        if self._notifications_manager is None:
            logger.debug(
                "Notifications manager not wired; skipping spawn confirmation for review %s",
                review_id,
            )
            return
        try:
            notification = Notification(
                id=str(uuid.uuid4()),
                recipient=requester_email,
                title="Term-mapping review created",
                description=(
                    f"Review request for run {run_id} created with "
                    f"{suggestion_count} suggestion(s); assigned to {reviewer_email}."
                ),
                type=NotificationType.INFO,
                link=f"/data-asset-reviews/{review_id}",
                created_at=_utcnow(),
            )
            self._notifications_manager.create_notification(notification)
        except Exception:
            logger.exception(
                "Failed to send spawn-confirmation notification for review %s",
                review_id,
            )

    # ------------------------------------------------------------------
    # Inline suggester (ConceptSelectDialog)
    # ------------------------------------------------------------------
    def suggest_inline(
        self,
        db: Session,
        *,
        payload: InlineSuggestRequest,
    ) -> InlineSuggestResponse:
        """Cheap heuristic suggestions for one entity, no persistence.

        Reuses the run-time machinery (adapters → heuristic engine →
        concept source) but skips DB writes. Used by ConceptSelectDialog
        to inline the "Suggested by mapping" tier.

        Context selection is more permissive than bulk runs: when the
        caller doesn't specify ontology_contexts we fall back to every
        non-internal, non-shipped context in the graph (see
        ``resolve_inline_default_contexts``). This catches file-loaded
        customer ontologies (e.g. ``urn:demo``) that aren't formal
        ``urn:semantic-model:*`` rows. We still reject internal contexts
        outright."""
        if payload.ontology_contexts:
            contexts = list(payload.ontology_contexts)
        else:
            contexts = resolve_inline_default_contexts(self._smm)
        # Strip any explicitly-blocked context the caller tried to sneak in.
        contexts = [c for c in contexts if c not in INTERNAL_BLOCKED_CONTEXTS]
        # Shipped opt-ins still flow through the strict validator below
        # (they're a closed set anyway).
        try:
            shipped_effective = validate_contexts([], payload.include_shipped)
        except InvalidContextError as e:
            raise ValueError(str(e)) from e
        effective: List[str] = []
        for ctx in (*contexts, *shipped_effective):
            if ctx not in effective:
                effective.append(ctx)
        if not effective:
            return InlineSuggestResponse(
                source_entity_type=payload.source_entity_type,
                source_entity_id=payload.source_entity_id,
                suggestions=[],
            )

        # Locate the target via the adapter responsible for its entity type.
        target: Optional[TargetEntity] = None
        for adapter in all_adapters():
            if payload.source_entity_type in adapter.entity_types:
                target = adapter.get_target(db, payload.source_entity_id)
                if target is not None:
                    break
        # Synthetic-target fallback: the entity hasn't been persisted yet
        # (e.g. a property being typed into a form). Build a transient
        # TargetEntity from the optional hints on the request so the
        # suggester can still propose matches based on the name alone.
        if target is None and payload.name:
            target = TargetEntity(
                entity_type=payload.source_entity_type,
                entity_id=payload.source_entity_id,
                name=payload.name,
                label=payload.name,
                type_label=payload.type_label or "",
                parent_name=payload.parent_name,
            )
        if target is None:
            return InlineSuggestResponse(
                source_entity_type=payload.source_entity_type,
                source_entity_id=payload.source_entity_id,
                suggestions=[],
            )

        source = ConceptSource(self._smm, effective)
        engine = HeuristicSuggester(concepts=source, already_decided=lambda *_a, **_k: False)
        drafts = engine.suggest([target])
        # Sort highest-confidence first, drop NEW: sentinels, cap to limit.
        ranked = sorted(
            (d for d in drafts if not (d.target_concept_iri or "").startswith("NEW:")),
            key=lambda d: d.confidence,
            reverse=True,
        )[: max(1, payload.limit)]
        return InlineSuggestResponse(
            source_entity_type=payload.source_entity_type,
            source_entity_id=payload.source_entity_id,
            suggestions=[
                InlineSuggestion(
                    target_concept_iri=d.target_concept_iri,
                    target_concept_label=d.target_concept_label,
                    confidence=d.confidence,
                    reason=d.reason,
                    auto_apply=d.auto_apply,
                )
                for d in ranked
            ],
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
