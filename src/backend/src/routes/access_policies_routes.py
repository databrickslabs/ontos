"""API routes for Access Policies (W3C ODRL 2.2): policies, audiences, asset collections, targets."""
from typing import Any, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from src.common import odrl
from src.common import policy_targets as pt
from src.common.authorization import (
    PermissionChecker,
    enforce_feature_permission,
    get_user_groups,
    is_user_feature_admin,
)
from src.common.dependencies import AuditCurrentUserDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.manager_dependencies import get_delivery_service
from src.controller.access_policies_manager import (
    KIND_ASSET_COLLECTION,
    KIND_AUDIENCE,
    KIND_POLICY,
    KIND_TARGET,
    AccessPoliciesManager,
    AccessPolicyError,
)
from src.controller.access_policy_releases_manager import (
    PolicyReleaseManager,
    uc_object_kind_resolver,
)
from src.models.access_policies import (
    AccessPolicyCreate,
    AccessPolicyUpdate,
    CheckAccessRequest,
    CollectionCreate,
    CollectionUpdate,
    DutyFulfillRequest,
    NewVersionRequest,
    PolicyImportRequest,
    PolicyValidateRequest,
    ReleaseConfirmRequest,
    ReleaseCreateRequest,
    ReleaseDeliverRequest,
    ReleasePreviewRequest,
    RevokeExpiredRequest,
    StatusChangeRequest,
    TargetCreate,
    TargetUpdate,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/access-policies", tags=["Access Policies"])
manager = AccessPoliciesManager()
releases = PolicyReleaseManager(manager)

FEATURE_ID = "access-policies"
_READ = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))
_WRITE = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))
# Delivering grants to a platform is an administrative action.
_ADMIN = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.ADMIN))

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


async def _subject_guard(request: Request, db: Any, user: Any) -> Any:
    """Who may make an Offer the terms of a Data Product: an Access Policies admin, or the
    product's owners — a member of its owner team or of its project (membership-based, no
    substring-admin shortcut)."""
    email = _email(user)
    is_admin = await _is_admin(request, user)
    try:
        groups = await get_user_groups(email, request) if email else []
    except Exception:  # pragma: no cover - auth backends vary per env
        groups = []

    def can_manage(product: Any) -> bool:
        if is_admin:
            return True
        if not email:
            return False
        try:
            from src.controller.teams_manager import teams_manager
            if product.owner_team_id and any(str(getattr(t, "id", "")) == str(product.owner_team_id)
                                             for t in teams_manager.get_teams_for_user(db, email, groups)):
                return True
            if product.project_id:
                from src.common.config import get_settings
                from src.controller.projects_manager import projects_manager
                return bool(projects_manager.is_user_project_member(
                    db=db, user_identifier=email, user_groups=groups or [],
                    project_id=str(product.project_id), settings=get_settings()))
        except Exception:  # pragma: no cover - fail closed
            logger.exception("Ownership check for Offer subject failed")
        return False
    return can_manage


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


@router.get("/agreements/{entity_id}")
async def agreement_for_party(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep):
    """An Agreement as its party sees it: what it grants, the terms it binds, and the open duties."""
    from src.controller import access_agreements
    is_admin = await _is_admin(request, current_user)
    row = await _agreement_for_party(request, db, current_user, entity_id, is_admin)
    body = row.body or {}

    def brief(rules: List[Any]) -> List[Any]:
        return [{"action": r.get("action"), "target": r.get("target"),
                 "constraint": r.get("constraint") or []} for r in rules or []]
    return {
        "id": row.id, "name": row.name, "description": row.description, "status": row.status,
        "policy_type": row.policy_type, "access_grant_id": row.access_grant_id,
        "permissions": brief(body.get("permission")), "prohibitions": brief(body.get("prohibition")),
        "obligations": brief(body.get("obligation")),
        "duties": access_agreements.duty_status(row, _email(current_user), is_admin),
    }


@router.get("/policies/{entity_id}/duties")
async def agreement_duties(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep):
    """Duties on an Agreement: which are fulfilled, and which the caller may fulfil.

    Readable by the Agreement's own assignee (consumers usually lack the Access Policies feature)
    or with Access Policies read access."""
    from src.controller import access_agreements
    is_admin = await _is_admin(request, current_user)
    row = await _agreement_for_party(request, db, current_user, entity_id, is_admin)
    return access_agreements.duty_status(row, _email(current_user), is_admin)


async def _agreement_for_party(request: Request, db: Any, user: Any, entity_id: str, is_admin: bool) -> Any:
    """The Agreement if the caller is its assignee or may read Access Policies; 404 otherwise."""
    from src.controller import access_agreements
    from src.db_models.access_policies import AccessPolicyDb
    row = db.get(AccessPolicyDb, entity_id)
    email = (_email(user) or "").lower()
    if row is not None and row.policy_type == "Agreement" and email in access_agreements._assignee_emails(row):
        return row
    try:
        await enforce_feature_permission(FEATURE_ID, FeatureAccessLevel.READ_ONLY, user, request)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Access Policy not found") from None
    try:
        return manager.require_visible(db, KIND_POLICY, entity_id, _email(user), is_admin)
    except AccessPolicyError as e:
        raise _http(e) from None


@router.post("/policies/{entity_id}/duties/fulfill")
async def fulfill_agreement_duty(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                                 payload: DutyFulfillRequest = Body(...)):
    """Fulfil a duty: the grantee accepts the terms (read access is enough — it's their own deal);
    other duties need an Access Policies admin. With auto-delivery on, now-unconditional grants ship."""
    from src.controller import access_agreements
    is_admin = await _is_admin(request, current_user)
    try:
        row = await _agreement_for_party(request, db, current_user, entity_id, is_admin)
        row = access_agreements.fulfill_duty(db, row, payload.action, _email(current_user), is_admin, payload.note)
        db.commit()
    except AccessPolicyError as e:
        raise _http(e)
    if not access_agreements.open_duties(row):
        access_agreements.auto_deliver(db, [row], _email(current_user), revoke=False)
    return access_agreements.duty_status(row, _email(current_user), is_admin)


@router.get("/offers")
async def offers_for_entity(request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            entity_type: str = Query(..., description="data_product"),
                            entity_id: str = Query(...),
                            include_inactive: bool = Query(False), _: bool = _READ):
    """Offers (terms of use) stated for an entity, e.g. a Data Product's access terms."""
    is_admin = await _is_admin(request, current_user)
    rows = [r for r in manager.offers_for(db, entity_type, entity_id, active_only=not include_inactive)
            if manager._visible(r, _email(current_user), is_admin)]
    manager.prefetch_subject_names(db, rows)
    return [manager.to_read_dict(db, KIND_POLICY, r) for r in rows]


# ------------------------------------------------- releases & ledger (Phase 2)

def _grant_manager(delivery_service: Any) -> Any:
    gm = delivery_service.grant_manager if delivery_service else None
    if gm is None:
        try:
            from src.controller.grant_manager import get_grant_manager
            gm = get_grant_manager()
        except RuntimeError:
            return None
    return gm


def _kind_resolver(delivery_service: Any) -> Any:
    gm = _grant_manager(delivery_service)
    ws = getattr(gm, "workspace_client", None) if gm else None
    return uc_object_kind_resolver(ws) if ws else None


@router.get("/compile-targets")
async def list_compile_targets(db: DBSessionDep, delivery_service: Any = Depends(get_delivery_service),
                               _: bool = _READ):
    """Targets releases can compile for, the available adapters, and the Delivery Modes enabled in Settings."""
    modes = [m.value for m in delivery_service.get_active_modes()] if delivery_service else []
    return {"targets": [t.to_dict() for t in releases.targets(db)],
            "systems": [a.describe() for a in pt.adapters()], "delivery_modes": modes}


# Endpoints below that call the Databricks SDK (grants, object-kind lookups) are plain ``def``
# so FastAPI runs them in the threadpool instead of blocking the event loop.
@router.post("/releases/preview")
def preview_release(db: DBSessionDep, payload: ReleasePreviewRequest = Body(...),
                          delivery_service: Any = Depends(get_delivery_service), _: bool = _READ):
    """Compile active policies for a target and diff against the Grant Ledger, without saving."""
    try:
        return releases.compile(db, payload.target, resolve_object_kind=_kind_resolver(delivery_service))
    except AccessPolicyError as e:
        raise _http(e)


@router.get("/releases")
async def list_releases(db: DBSessionDep, target: Optional[str] = Query(None), status: Optional[str] = Query(None),
                        _: bool = _READ):
    return [releases.to_read_dict(r) for r in releases.list(db, target, status)]


@router.post("/releases", status_code=201)
def create_release(db: DBSessionDep, current_user: AuditCurrentUserDep,
                         payload: ReleaseCreateRequest = Body(...),
                         delivery_service: Any = Depends(get_delivery_service), _: bool = _WRITE):
    try:
        row = releases.create_release(db, payload.target, _email(current_user), payload.notes,
                                      resolve_object_kind=_kind_resolver(delivery_service))
    except AccessPolicyError as e:
        raise _http(e)
    return releases.to_read_dict(row)


@router.get("/releases/{release_id}")
async def get_release(release_id: str, db: DBSessionDep, _: bool = _READ):
    try:
        return releases.to_read_dict(releases.require(db, release_id))
    except AccessPolicyError as e:
        raise _http(e)


@router.post("/releases/{release_id}/recompile")
def recompile_release(release_id: str, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            delivery_service: Any = Depends(get_delivery_service), _: bool = _WRITE):
    try:
        row = releases.recompile(db, release_id, _email(current_user), resolve_object_kind=_kind_resolver(delivery_service))
    except AccessPolicyError as e:
        raise _http(e)
    return releases.to_read_dict(row)


@router.post("/releases/{release_id}/status")
async def change_release_status(release_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                                payload: StatusChangeRequest = Body(...), _: bool = _WRITE):
    try:
        row = releases.change_status(db, release_id, payload.status, _email(current_user), payload.comment,
                                     is_admin=await _is_admin(request, current_user))
    except AccessPolicyError as e:
        raise _http(e)
    return releases.to_read_dict(row)


@router.post("/releases/{release_id}/deliver")
def deliver_release(release_id: str, db: DBSessionDep, current_user: AuditCurrentUserDep,
                          payload: ReleaseDeliverRequest = Body(default_factory=ReleaseDeliverRequest),
                          delivery_service: Any = Depends(get_delivery_service), _: bool = _ADMIN):
    """Ship an approved release through the chosen Delivery Modes."""
    try:
        row = releases.deliver(db, release_id, _email(current_user), delivery_service, payload.modes)
    except (AccessPolicyError, ValueError) as e:
        raise _http(e if isinstance(e, AccessPolicyError) else AccessPolicyError(str(e)))
    return releases.to_read_dict(row)


@router.post("/releases/{release_id}/confirm-applied")
def confirm_release_applied(release_id: str, db: DBSessionDep, current_user: AuditCurrentUserDep,
                                  payload: ReleaseConfirmRequest = Body(default_factory=ReleaseConfirmRequest),
                                  _: bool = _ADMIN):
    """Confirm an Indirect / Manual release was applied on the target; updates the Grant Ledger."""
    try:
        row = releases.confirm_applied(db, release_id, _email(current_user), payload.comment)
    except AccessPolicyError as e:
        raise _http(e)
    return releases.to_read_dict(row)


@router.post("/releases/{release_id}/live-diff")
def release_live_diff(release_id: str, db: DBSessionDep,
                            delivery_service: Any = Depends(get_delivery_service), _: bool = _WRITE):
    """Compare the release's desired grants with live Unity Catalog grants (report-only)."""
    gm = _grant_manager(delivery_service)
    if gm is None:
        raise HTTPException(status_code=503, detail="Grant manager is not configured")
    try:
        return releases.live_diff(db, release_id, gm.get_grants)
    except AccessPolicyError as e:
        raise _http(e)


@router.get("/ledger")
async def get_ledger(db: DBSessionDep, target: Optional[str] = Query(None),
                     status: Optional[str] = Query("active", description="active | revoked; empty for all"),
                     principal: Optional[str] = Query(None), _: bool = _READ):
    """Grants Ontos has applied and tracks (including expiry for time-bound access)."""
    return releases.ledger(db, target, status or None, principal)


@router.post("/ledger/revoke-expired")
def revoke_expired(db: DBSessionDep, current_user: AuditCurrentUserDep,
                         payload: RevokeExpiredRequest = Body(default_factory=RevokeExpiredRequest),
                         delivery_service: Any = Depends(get_delivery_service), _: bool = _ADMIN):
    """Create and deliver a revocation release for every expired ledger grant (schedule this as a job)."""
    try:
        row = releases.revoke_expired(db, payload.target, _email(current_user), delivery_service)
    except AccessPolicyError as e:
        raise _http(e)
    return {"release": releases.to_read_dict(row) if row else None,
            "revoked": (row.changes or {}).get("remove", []) if row else []}


# ------------------------------------------------- generic per-kind CRUD

def _register_kind(segment: str, kind: str, create_model: Any, update_model: Any, write: Any = _WRITE) -> None:
    """Register list/get/create/update/delete/versions/status for one entity kind (``write`` guards changes)."""

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
        if kind == KIND_POLICY:
            manager.prefetch_subject_names(db, rows)
        elif kind == KIND_TARGET:
            counts = manager.tracked_counts(db)
            for r in rows:
                r._tracked_grants = counts.get(r.key, 0)
        return [manager.to_read_dict(db, kind, r) for r in rows]

    async def get_entity(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                         _: bool = _READ):
        try:
            row = await _visible_row(request, db, current_user, entity_id)
        except AccessPolicyError as e:
            raise _http(e)
        return manager.to_read_dict(db, kind, row)

    async def create_entity(request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            payload: create_model = Body(...), _: bool = write):  # type: ignore[valid-type]
        try:
            guard = await _subject_guard(request, db, current_user) if kind == KIND_POLICY else None
            row = manager.create(db, kind, payload, _email(current_user), can_manage_subject=guard)
        except AccessPolicyError as e:
            raise _http(e)
        return manager.to_read_dict(db, kind, row)

    async def update_entity(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            payload: update_model = Body(...), _: bool = write):  # type: ignore[valid-type]
        try:
            await _visible_row(request, db, current_user, entity_id)
            guard = await _subject_guard(request, db, current_user) if kind == KIND_POLICY else None
            row = manager.update(db, kind, entity_id, payload, _email(current_user), can_manage_subject=guard)
        except AccessPolicyError as e:
            raise _http(e)
        return manager.to_read_dict(db, kind, row)

    async def delete_entity(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            _: bool = write):
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
                          payload: NewVersionRequest = Body(...), _: bool = write):
        try:
            await _visible_row(request, db, current_user, entity_id)
            row = manager.create_new_version(db, kind, entity_id, payload.new_version,
                                             payload.change_summary, _email(current_user))
        except AccessPolicyError as e:
            raise _http(e)
        return manager.to_read_dict(db, kind, row)

    async def change_status(entity_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
                            payload: StatusChangeRequest = Body(...), _: bool = write):
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
# Where grants get pushed is an administrative decision.
_register_kind("targets", KIND_TARGET, TargetCreate, TargetUpdate, write=_ADMIN)


def register_routes(app):
    """Register routes with the app"""
    app.include_router(router)
    logger.info("Access Policies routes registered")
