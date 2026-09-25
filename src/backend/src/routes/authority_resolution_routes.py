"""API routes for the Authority Resolution feature (ARF)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body, Query

from src.common.dependencies import DBSessionDep, AuditCurrentUserDep, DataAssetReviewManagerDep
from src.common.features import FeatureAccessLevel
from src.common.authorization import PermissionChecker
from src.controller.authority_resolution_manager import AuthorityResolutionManager
from src.models.authority_resolution import (
    AuthorityRelationCreate,
    AuthorityRelationUpdate,
    NewVersionRequest,
    StatusChangeRequest,
    AffirmRequest,
    ResolveRequest,
)

from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Authority Resolution"])
manager = AuthorityResolutionManager()

FEATURE_ID = "authority-resolution"


def _resolve_req_dict(req: ResolveRequest) -> dict:
    base = {
        "actor_identity": req.actor_identity,
        "action": req.action,
        "object_id": req.object_id,
        "value": req.value,
        "cosign_present": req.cosign_present,
        "escalated": req.escalated,
    }
    base.update(req.params or {})
    return base


@router.get("/authority/relations")
async def list_relations(
    db: DBSessionDep,
    domain_ids: Optional[str] = Query(None, description="CSV of domain ids (any-of filter)"),
    include_history: bool = Query(False, description="Return every version instead of one row per family"),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    ids = [d for d in domain_ids.split(",") if d] if domain_ids else None
    relations = manager.list_relations(db, domain_ids=ids, include_history=include_history)
    return [manager.to_read_dict(db, r) for r in relations]


@router.post("/authority/relations")
async def create_relation(
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: AuthorityRelationCreate = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    username = current_user.username if current_user else None
    relation = manager.create_relation(db, payload, current_user=username)
    return manager.to_read_dict(db, relation)


@router.get("/authority/relations/{relation_id}")
async def get_relation(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    # UUID pins the exact version (version navigation uses ids); a slug resolves
    # to the family's active version (the stable agent-facing @id).
    relation = manager.resolve_relation_ref(db, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return manager.to_read_dict(db, relation)


@router.put("/authority/relations/{relation_id}")
async def update_relation(
    relation_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: AuthorityRelationUpdate = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    username = current_user.username if current_user else None
    relation = manager.update_relation(db, relation_id, payload, current_user=username)
    if not relation:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return manager.to_read_dict(db, relation)


@router.delete("/authority/relations/{relation_id}")
async def delete_relation(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    if not manager.delete_relation(db, relation_id):
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return {"deleted": True, "id": relation_id}


@router.get("/authority/relations/{relation_id}/versions")
async def get_relation_versions(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Every version of an AR's family, newest first — the tight row shape the
    shared VersionSelector / VersionNavigator consumes (mirrors Data Products)."""
    try:
        rows = manager.get_relation_versions(db, relation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return [
        {
            "id": r.id,
            "name": r.name,
            "version": r.version,
            "status": r.status,
            "versionFamilyId": r.version_family_id,
            "parentRelationId": getattr(r, "parent_relation_id", None),
            "baseName": getattr(r, "base_name", None),
            "changeSummary": getattr(r, "change_summary", None),
            "draftOwnerId": getattr(r, "draft_owner_id", None),
            "createdAt": r.created_at.isoformat() if r.created_at else None,
            "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.post("/authority/relations/{relation_id}/versions", status_code=201)
async def create_relation_version(
    relation_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: NewVersionRequest = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Snapshot an AR into a new immutable version (deep-clones the definition)."""
    username = current_user.username if current_user else None
    relation = manager.create_new_version(
        db, relation_id, payload.new_version,
        change_summary=payload.change_summary, current_user=username,
    )
    if relation is None:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return manager.to_read_dict(db, relation)


@router.post("/authority/relations/{relation_id}/compute-dnaco")
async def compute_dnaco(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        run = manager.compute_dnaco(db, relation_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DNA-Coefficient computation failed: {e}")
    if not run:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return {
        "run_id": run.id, "status": run.status, "sampled_count": run.sampled_count,
        "divergent_count": run.divergent_count, "magnitude": run.magnitude, "direction": run.direction,
    }


@router.post("/authority/relations/{relation_id}/status")
async def change_status(
    relation_id: str,
    db: DBSessionDep,
    payload: StatusChangeRequest = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    relation, error = manager.set_status(db, relation_id, payload.status)
    if relation is None:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    if error:
        raise HTTPException(status_code=409, detail=error)
    return manager.to_read_dict(db, relation)


@router.post("/authority/affirmations/{affirmation_id}/affirm")
async def affirm(
    affirmation_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: AffirmRequest = Body(default=AffirmRequest()),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    username = current_user.username if current_user else "unknown"
    aff = manager.affirm(db, affirmation_id, affirmed_by=username, notes=payload.notes)
    if not aff:
        raise HTTPException(status_code=404, detail="Affirmation not found")
    return {"id": aff.id, "affirmed": aff.affirmed, "affirmed_by": aff.affirmed_by, "affirmed_at": aff.affirmed_at}


@router.post("/authority/relations/{relation_id}/resolve")
async def resolve(
    relation_id: str,
    db: DBSessionDep,
    payload: ResolveRequest = Body(default=ResolveRequest()),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return manager.resolve(db, relation_id, _resolve_req_dict(payload))


@router.post("/authority/relations/{relation_id}/test")
async def test_resolve(
    relation_id: str,
    db: DBSessionDep,
    payload: ResolveRequest = Body(default=ResolveRequest()),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Dry-run the resolution gate against this AR regardless of status, without
    recording the decision or touching the usage counters. Used by the detail-view
    Test dialog so authors can preview verdicts before activating.
    """
    return manager.resolve(db, relation_id, _resolve_req_dict(payload), record=False, require_active=False)


@router.get("/authority/relations/{relation_id}/decisions")
async def list_decisions(
    relation_id: str,
    db: DBSessionDep,
    source: Optional[str] = Query(None),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    from src.repositories.authority_resolution_repository import authority_decision_repo
    rows = authority_decision_repo.list_for_relation(db, relation_id=relation_id, source=source)
    return [
        {
            "id": d.id, "source": d.source, "verdict": d.verdict, "reason": d.reason,
            "actor_identity": d.actor_identity, "action": d.action, "object_id": d.object_id,
            "relation_version": d.relation_version, "divergence_magnitude": d.divergence_magnitude,
            "created_at": d.created_at,
        }
        for d in rows
    ]


@router.get("/authority/relations/{relation_id}/dna-runs")
async def list_dna_runs(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    from src.repositories.authority_resolution_repository import authority_dna_run_repo
    runs = authority_dna_run_repo.list_for_relation(db, relation_id=relation_id)
    return [
        {
            "id": r.id, "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at,
            "sampled_count": r.sampled_count, "divergent_count": r.divergent_count,
            "magnitude": r.magnitude, "direction": r.direction, "error_message": r.error_message,
        }
        for r in runs
    ]


@router.post("/authority/relations/{relation_id}/start-review")
async def start_review(
    relation_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    reviews_manager: DataAssetReviewManagerDep,
    payload: dict = Body(default={}),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    owner = current_user.username if current_user else None
    message = payload.get("message") if isinstance(payload, dict) else None
    result = manager.start_review(db, relation_id, owner=owner, reviews_manager=reviews_manager, message=message)
    if result is None:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return result


@router.get("/authority/relations/{relation_id}/criteria")
async def list_criteria(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """The AR's author-configured decision criteria (Compliance Checks + facets)."""
    relation = manager.get_relation(db, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return manager.to_read_dict(db, relation).get("criteria", [])


@router.get("/authority/criteria/policies")
async def list_reusable_checks(
    db: DBSessionDep,
    category: Optional[str] = Query(None, description="Filter by compliance policy category"),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Reusable Compliance Checks for the criteria picker (authority-scoped so the
    builder isn't gated on the separate compliance permission)."""
    from src.db_models.compliance import CompliancePolicyDb
    q = db.query(CompliancePolicyDb).filter(CompliancePolicyDb.is_active == True)  # noqa: E712
    if category:
        q = q.filter(CompliancePolicyDb.category == category)
    return [
        {
            "id": p.id, "name": p.name, "rule": p.rule, "category": p.category,
            "failure_message": p.failure_message, "severity": p.severity,
        }
        for p in q.order_by(CompliancePolicyDb.name.asc()).all()
    ]


@router.post("/authority/criteria/validate")
async def validate_criterion(
    db: DBSessionDep,
    payload: dict = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Live-validate a single criterion's DSL rule against a sample request object.

    Body: ``{rule, object}``. The ``ASSERT`` keyword is prepended if omitted.
    Returns ``{passed, message}``.
    """
    from src.common.compliance_dsl import evaluate_rule_on_object as eval_dsl
    rule = (payload.get("rule") or "").strip()
    if rule and not rule.upper().startswith("ASSERT"):
        rule = "ASSERT " + rule
    obj = payload.get("object") or {}
    try:
        passed, msg = eval_dsl(rule, obj)
        return {"passed": passed, "message": msg}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Rule validation failed: {e}")


@router.post("/authority/recompute-scheduled")
async def recompute_scheduled(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Manually trigger a DNAco recompute for every AR with a schedule set.

    The same routine the scheduled ``authority_dna_recompute`` job runs.
    """
    return manager.recompute_scheduled(db)


@router.get("/authority/relations/{relation_id}/review-tracking")
async def review_tracking(
    relation_id: str,
    db: DBSessionDep,
    reviews_manager: DataAssetReviewManagerDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    result = manager.get_review_tracking(db, relation_id, reviews_manager=reviews_manager)
    if result is None:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return result


@router.get("/authority/relations/{relation_id}/review-context")
async def review_context(
    relation_id: str,
    db: DBSessionDep,
    reviewer: str = Query(..., description="Reviewer principal (email/group)"),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    ctx = manager.get_review_context(db, relation_id, reviewer)
    if ctx is None:
        raise HTTPException(status_code=404, detail="No review found for this reviewer on this Authority Relation")
    return ctx


@router.post("/authority/participants/{participant_id}/submit-review")
async def submit_review(
    participant_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: dict = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    reviewer = current_user.username if current_user else None
    answers = payload.get("answers", payload) if isinstance(payload, dict) else {}
    participant = manager.submit_review(db, participant_id, answers=answers, reviewer=reviewer)
    if not participant:
        raise HTTPException(status_code=404, detail="Review participant not found")
    return {"id": participant.id, "review_status": participant.review_status}


def register_routes(app):
    """Register the Authority Resolution routes with the FastAPI app."""
    app.include_router(router)
