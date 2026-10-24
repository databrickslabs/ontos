"""API routes for Access Policies (W3C ODRL 2.2): policies, audiences, asset collections."""
from typing import Any, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from src.common import odrl
from src.common.authorization import PermissionChecker, get_user_groups, is_user_feature_admin
from src.common.dependencies import AuditCurrentUserDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.access_policies_manager import (
    KIND_ASSET_COLLECTION,
    KIND_AUDIENCE,
    KIND_POLICY,
    AccessPoliciesManager,
    AccessPolicyError,
)
from src.models.access_policies import (
    AccessPolicyCreate,
    AccessPolicyUpdate,
    CheckAccessRequest,
    CollectionCreate,
    CollectionUpdate,
    NewVersionRequest,
    PolicyImportRequest,
    PolicyValidateRequest,
    StatusChangeRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/access-policies", tags=["Access Policies"])
manager = AccessPoliciesManager()

FEATURE_ID = "access-policies"
_READ = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))
_WRITE = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))

def _email(user: Any) -> Optional[str]:
    return (getattr(user, "email", None) or getattr(user, "username", None)) if user else None


def _http(e: AccessPolicyError) -> HTTPException:
    detail: Any = str(e)
    if e.details:
        detail = {"message": str(e), "problems": e.details}
    return HTTPException(status_code=e.status_code, detail=detail)


async def _is_admin(request: Request, user: Any) -> bool:
    email = _email(user)
    if not email:
        return False
    try:
        groups = await get_user_groups(email, request)
        return await is_user_feature_admin(email, groups, FEATURE_ID, request)
    except Exception:  # pragma: no cover - auth backends vary per env
        return False


# ------------------------------------------------------------------ profile

@router.get("/profile")
async def get_profile(_: bool = _READ):
    """The Ontos ODRL profile vocabulary (actions, left operands, operators)."""
    return odrl.profile_vocabulary()


@router.post("/validate")
async def validate_policy(db: DBSessionDep, payload: PolicyValidateRequest = Body(...), _: bool = _READ):
    issues = manager.validate_body(db, payload.policy_type, payload.conflict, payload.inherit_from, payload.rules)
    return {"valid": not any(i["severity"] == "error" for i in issues), "issues": issues}


@router.post("/check-access")
async def check_access(request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                       payload: CheckAccessRequest = Body(...), _: bool = _READ):
    """Evaluate "can principal do action on asset?" against active policies (or a what-if set)."""
    return manager.check_access(db, payload, viewer=_email(current_user), is_admin=await _is_admin(request, current_user))


@router.post("/policies/import", status_code=201)
async def import_policy(db: DBSessionDep, current_user: AuditCurrentUserDep,
                        payload: PolicyImportRequest = Body(...), _: bool = _WRITE):
    try:
        row = manager.import_jsonld(db, payload, _email(current_user))
    except AccessPolicyError as e:
        raise _http(e)
    return manager.to_read_dict(db, KIND_POLICY, row)


@router.get("/policies/{entity_id}/jsonld")
async def export_policy(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                        _: bool = _READ):
    try:
        row = manager.require_visible(db, KIND_POLICY, entity_id, _email(current_user), await _is_admin(request, current_user))
    except AccessPolicyError as e:
        raise _http(e)
    return manager.to_jsonld(db, row)


@router.get("/policies/{entity_id}/validation")
async def policy_validation(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            _: bool = _READ):
    try:
        row = manager.require_visible(db, KIND_POLICY, entity_id, _email(current_user), await _is_admin(request, current_user))
    except AccessPolicyError as e:
        raise _http(e)
    issues = manager.validate_body(db, row.policy_type, row.conflict, row.inherit_from or [], row.body or {})
    return {
        "valid": not any(i["severity"] == "error" for i in issues),
        "issues": issues,
        "activation_problems": manager.activation_problems(db, KIND_POLICY, row),
    }


# ------------------------------------------------- generic per-kind CRUD

def _register_kind(segment: str, kind: str, create_model: Any, update_model: Any) -> None:
    """Register list/get/create/update/delete/versions/status for one entity kind."""

    async def _visible_row(request: Request, db: Any, current_user: Any, entity_id: str) -> Any:
        return manager.require_visible(db, kind, entity_id, _email(current_user), await _is_admin(request, current_user))

    async def list_entities(
        request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
        include_history: bool = Query(False, description="Return every version instead of one per family"),
        status: Optional[str] = Query(None),
        _: bool = _READ,
    ):
        is_admin = await _is_admin(request, current_user)
        rows = manager.list(db, kind, include_history=include_history, status=status,
                            viewer=_email(current_user), is_admin=is_admin)
        return [manager.to_read_dict(db, kind, r) for r in rows]

    async def get_entity(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                         _: bool = _READ):
        try:
            row = await _visible_row(request, db, current_user, entity_id)
        except AccessPolicyError as e:
            raise _http(e)
        return manager.to_read_dict(db, kind, row)

    async def create_entity(db: DBSessionDep, current_user: AuditCurrentUserDep,
                            payload: create_model = Body(...), _: bool = _WRITE):  # type: ignore[valid-type]
        try:
            row = manager.create(db, kind, payload, _email(current_user))
        except AccessPolicyError as e:
            raise _http(e)
        return manager.to_read_dict(db, kind, row)

    async def update_entity(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            payload: update_model = Body(...), _: bool = _WRITE):  # type: ignore[valid-type]
        try:
            await _visible_row(request, db, current_user, entity_id)
            row = manager.update(db, kind, entity_id, payload, _email(current_user))
        except AccessPolicyError as e:
            raise _http(e)
        return manager.to_read_dict(db, kind, row)

    async def delete_entity(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            _: bool = _WRITE):
        try:
            await _visible_row(request, db, current_user, entity_id)
            manager.delete(db, kind, entity_id, _email(current_user))
        except AccessPolicyError as e:
            raise _http(e)
        return {"deleted": entity_id}

    async def list_versions(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            _: bool = _READ):
        try:
            await _visible_row(request, db, current_user, entity_id)
            is_admin = await _is_admin(request, current_user)
            rows = [r for r in manager.versions(db, kind, entity_id)
                    if manager._visible(r, _email(current_user), is_admin)]
        except AccessPolicyError as e:
            raise _http(e)
        return [
            {"id": r.id, "name": r.name, "version": r.version, "status": r.status,
             "parent_id": r.parent_id, "change_summary": r.change_summary,
             "created_at": r.created_at, "created_by": r.created_by,
             # camelCase twins for the shared VersionSelector (EntityVersionRow).
             "versionFamilyId": r.version_family_id, "changeSummary": r.change_summary,
             "draftOwnerId": r.draft_owner_id, "createdAt": r.created_at}
            for r in rows
        ]

    async def new_version(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                          payload: NewVersionRequest = Body(...), _: bool = _WRITE):
        try:
            await _visible_row(request, db, current_user, entity_id)
            row = manager.create_new_version(db, kind, entity_id, payload.new_version,
                                             payload.change_summary, _email(current_user))
        except AccessPolicyError as e:
            raise _http(e)
        return manager.to_read_dict(db, kind, row)

    async def change_status(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            payload: StatusChangeRequest = Body(...), _: bool = _WRITE):
        try:
            await _visible_row(request, db, current_user, entity_id)
            row = manager.change_status(db, kind, entity_id, payload.status, _email(current_user), payload.comment,
                                        is_admin=await _is_admin(request, current_user))
        except AccessPolicyError as e:
            raise _http(e)
        return manager.to_read_dict(db, kind, row)

    base = f"/{segment}"
    label = manager.spec(kind).label
    routes: List[tuple] = [
        ("GET", base, list_entities, None),
        ("POST", base, create_entity, 201),
        ("GET", base + "/{entity_id}", get_entity, None),
        ("PUT", base + "/{entity_id}", update_entity, None),
        ("DELETE", base + "/{entity_id}", delete_entity, None),
        ("GET", base + "/{entity_id}/versions", list_versions, None),
        ("POST", base + "/{entity_id}/versions", new_version, 201),
        ("POST", base + "/{entity_id}/status", change_status, None),
    ]
    for method, path, fn, code in routes:
        fn.__name__ = f"{fn.__name__}_{kind}"
        kwargs: dict = {"methods": [method], "name": f"{fn.__name__}", "summary": f"{fn.__name__.split('_' + kind)[0].replace('_', ' ').capitalize()} ({label})"}
        if code:
            kwargs["status_code"] = code
        router.add_api_route(path, fn, **kwargs)


_register_kind("policies", KIND_POLICY, AccessPolicyCreate, AccessPolicyUpdate)
_register_kind("audiences", KIND_AUDIENCE, CollectionCreate, CollectionUpdate)
_register_kind("asset-collections", KIND_ASSET_COLLECTION, CollectionCreate, CollectionUpdate)


def register_routes(app):
    """Register routes with the app"""
    app.include_router(router)
    logger.info("Access Policies routes registered")
