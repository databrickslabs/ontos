"""API routes for the Authority Resolution feature (ARF)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body, Query

from src.common.dependencies import DBSessionDep, AuditCurrentUserDep
from src.common.features import FeatureAccessLevel
from src.common.authorization import PermissionChecker
from src.controller.authority_resolution_manager import AuthorityResolutionManager
from src.models.authority_resolution import (
    AuthorityRelationCreate,
    AuthorityRelationUpdate,
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
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    ids = [d for d in domain_ids.split(",") if d] if domain_ids else None
    relations = manager.list_relations(db, domain_ids=ids)
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
    relation = manager.get_relation(db, relation_id) or manager.get_relation_by_slug(db, relation_id)
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


def register_routes(app):
    """Register the Authority Resolution routes with the FastAPI app."""
    app.include_router(router)
