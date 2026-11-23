"""API routes for Policy references (the ARF justification metadata, ARF 1.2.0).

Read-only users see references; Read-write users create, edit, version and delete
them. Every change writes an audit record through the app's audit service, and
errors are coded (``{code, message, params}``).
"""
from fastapi import APIRouter, Body, Depends, Query, Request

from src.common.api_errors import coded_http_error
from src.common.authorization import PermissionChecker
from src.common.dependencies import AuditCurrentUserDep, AuditManagerDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.controller.authority_policy_manager import (
    AuthorityPolicyError,
    AuthorityPolicyManager,
    AuthorityPolicyNotFoundError,
)
from src.models.authority_policy import (
    AuthorityPolicyCreate,
    AuthorityPolicyUpdate,
    PolicyNewVersionRequest,
)

router = APIRouter(prefix="/api", tags=["Authority Resolution"])
manager = AuthorityPolicyManager()

FEATURE_ID = "authority-resolution"


def _user(current_user) -> str | None:
    return current_user.username if current_user else None


def _get_or_404(db, policy_id: str):
    policy = manager.get_policy(db, policy_id)
    if not policy:
        raise coded_http_error("get policy reference", AuthorityPolicyNotFoundError("Policy reference not found."))
    return policy


def _audit(audit_manager, db, request: Request, current_user, action: str, policy, details=None) -> None:
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else "unknown",
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action=action,
        success=True,
        details={
            "policy_id": policy.id,
            "policy_key": policy.policy_key,
            "version": policy.version,
            **(details or {}),
        },
    )


@router.get("/authority/policies")
async def list_policies(
    db: DBSessionDep,
    include_history: bool = Query(False, description="Return every version instead of one row per family"),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return [manager.to_read_dict(db, p) for p in manager.list_policies(db, include_history=include_history)]


@router.post("/authority/policies", status_code=201)
async def create_policy(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: AuthorityPolicyCreate = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        policy = manager.create_policy(db, payload, current_user=_user(current_user))
    except AuthorityPolicyError as e:
        raise coded_http_error("policy reference", e)
    _audit(audit_manager, db, request, current_user, "CREATE_POLICY_REFERENCE", policy)
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
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: AuthorityPolicyUpdate = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        policy = manager.update_policy(db, policy_id, payload, current_user=_user(current_user))
    except AuthorityPolicyError as e:
        raise coded_http_error("policy reference", e)
    if not policy:
        raise coded_http_error("update policy reference", AuthorityPolicyNotFoundError("Policy reference not found."))
    _audit(audit_manager, db, request, current_user, "UPDATE_POLICY_REFERENCE", policy)
    return manager.to_read_dict(db, policy)


@router.delete("/authority/policies/{policy_id}")
async def delete_policy(
    policy_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    policy = _get_or_404(db, policy_id)
    try:
        manager.delete_policy(db, policy_id)
    except AuthorityPolicyError as e:
        raise coded_http_error("policy reference", e)
    _audit(audit_manager, db, request, current_user, "DELETE_POLICY_REFERENCE", policy)
    return {"deleted": True, "id": policy_id}


@router.get("/authority/policies/{policy_id}/versions")
async def get_policy_versions(
    policy_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Every version of the reference's family, newest first (VersionNavigator shape)."""
    try:
        rows = manager.get_versions(db, policy_id)
    except AuthorityPolicyError as e:
        raise coded_http_error("policy reference", e)
    return [
        {
            "id": r.id,
            "name": r.title,
            "version": r.version,
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
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: PolicyNewVersionRequest = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """A new record for a new version of the source document (``parent_policy_id`` = this one)."""
    try:
        policy = manager.create_new_version(
            db, policy_id, payload.new_version,
            change_summary=payload.change_summary, current_user=_user(current_user),
        )
    except AuthorityPolicyError as e:
        raise coded_http_error("policy reference", e)
    if policy is None:
        raise coded_http_error("update policy reference", AuthorityPolicyNotFoundError("Policy reference not found."))
    _audit(audit_manager, db, request, current_user, "CREATE_POLICY_REFERENCE_VERSION", policy,
           details={"parent_policy_id": policy.parent_policy_id})
    return manager.to_read_dict(db, policy)


@router.get("/authority/policies/{policy_id}/dependents")
async def policy_dependents(
    policy_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """The cited-by list: Authority Relations (any version) citing this reference."""
    _get_or_404(db, policy_id)
    return manager.dependents(db, policy_id)


def register_routes(app):
    """Register the Policy reference routes with the FastAPI app."""
    app.include_router(router)
