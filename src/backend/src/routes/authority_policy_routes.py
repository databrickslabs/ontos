"""API routes for Authority Policies (the ARF justification basis)."""
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.common.authorization import PermissionChecker
from src.common.dependencies import AuditCurrentUserDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.controller.authority_policy_manager import AuthorityPolicyManager
from src.models.authority_policy import (
    AuthorityPolicyCreate,
    AuthorityPolicyUpdate,
    PolicyNewVersionRequest,
    PolicyStatusRequest,
)
from src.routes.authority_resolution_routes import manager as relation_manager

router = APIRouter(prefix="/api", tags=["Authority Resolution"])
manager = AuthorityPolicyManager(relation_manager=relation_manager)

FEATURE_ID = "authority-resolution"


def _user(current_user) -> str | None:
    return current_user.username if current_user else None


def _get_or_404(db, policy_id: str):
    policy = manager.get_policy(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Authority Policy not found")
    return policy


@router.get("/authority/policies")
async def list_policies(
    db: DBSessionDep,
    include_history: bool = Query(False, description="Return every version instead of one row per family"),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return [manager.to_read_dict(db, p) for p in manager.list_policies(db, include_history=include_history)]


@router.post("/authority/policies", status_code=201)
async def create_policy(
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: AuthorityPolicyCreate = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        policy = manager.create_policy(db, payload, current_user=_user(current_user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return manager.to_read_dict(db, policy)


@router.get("/authority/policies/{policy_id}")
async def get_policy(
    policy_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return manager.to_read_dict(db, _get_or_404(db, policy_id))


@router.put("/authority/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: AuthorityPolicyUpdate = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        policy = manager.update_policy(db, policy_id, payload, current_user=_user(current_user))
    except PermissionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not policy:
        raise HTTPException(status_code=404, detail="Authority Policy not found")
    return manager.to_read_dict(db, policy)


@router.delete("/authority/policies/{policy_id}")
async def delete_policy(
    policy_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        deleted = manager.delete_policy(db, policy_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Authority Policy not found")
    return {"deleted": True, "id": policy_id}


@router.get("/authority/policies/{policy_id}/versions")
async def get_policy_versions(
    policy_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Every version of the policy's family, newest first (VersionNavigator shape)."""
    try:
        rows = manager.get_versions(db, policy_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Authority Policy not found")
    return [
        {
            "id": r.id,
            "name": r.title,
            "version": r.version,
            "status": r.status,
            "versionFamilyId": r.version_family_id,
            "parentPolicyId": r.parent_policy_id,
            "changeSummary": r.change_summary,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
            "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.post("/authority/policies/{policy_id}/versions", status_code=201)
async def create_policy_version(
    policy_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: PolicyNewVersionRequest = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Draft a successor version (``wasDerivedFrom`` this one)."""
    try:
        policy = manager.create_new_version(
            db, policy_id, payload.new_version,
            change_summary=payload.change_summary, current_user=_user(current_user),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if policy is None:
        raise HTTPException(status_code=404, detail="Authority Policy not found")
    return manager.to_read_dict(db, policy)


@router.post("/authority/policies/{policy_id}/status")
async def change_policy_status(
    policy_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: PolicyStatusRequest = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Approve (supersedes the parent version) or withdraw (flags citing ARs)."""
    policy, error = manager.set_status(db, policy_id, payload, current_user=_user(current_user))
    if policy is None:
        raise HTTPException(status_code=404, detail="Authority Policy not found")
    if error:
        raise HTTPException(status_code=409, detail=error)
    return manager.to_read_dict(db, policy)


@router.get("/authority/policies/{policy_id}/dependents")
async def policy_dependents(
    policy_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Authority Relations (any version) citing this policy version."""
    _get_or_404(db, policy_id)
    return manager.dependents(db, policy_id)


def register_routes(app):
    """Register the Authority Policy routes with the FastAPI app."""
    app.include_router(router)
