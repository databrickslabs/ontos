"""Lifecycle Stage Groups (#1213): the groups (Settings) and an entity's lifecycle.

- ``GET /api/lifecycle-stage-groups?entity_type=`` and ``GET .../{id}``: read
  access to the entity type's feature (data-products, data-contracts, assets),
  or ``settings-lifecycle-stage-groups`` without an entity type.
- ``POST`` / ``PUT`` / ``DELETE /api/lifecycle-stage-groups[/{id}]``:
  ``settings-lifecycle-stage-groups`` Read/Write. A save replaces the group's
  stages and transitions and is validated (one first stage, all stages
  reachable from it, an active stage); a stage in use or named by a workflow
  rule can't be removed, a default or assigned group can't be deleted.
- ``GET /api/lifecycle/{entity_type}/{entity_id}``: the entity's group, stage and
  allowed next stages, for whoever may read the entity, and whether the caller
  may change its group (``can_change_group``).
- ``POST /api/lifecycle/{entity_type}/{entity_id}/change-group``: admins of the
  entity's feature or its owners; resets the status to the new group's first
  stage, writes a change-log entry, refused while a workflow request is pending.

Errors are coded (``{code, message, params}``): 400 invalid group or stage,
404 unknown group or entity, 409 integrity conflicts.
"""
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.common.api_errors import CodedValueError
from src.common.authorization import PermissionChecker, has_feature_permission
from src.common.dependencies import AuditCurrentUserDep, AuditManagerDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.lifecycle_service import (
    LifecycleActionUnresolvedError, LifecycleGroupConflictError, LifecycleGroupInvalidError,
    LifecycleGroupNotFoundError, lifecycle_service,
)
from src.models.lifecycle_stage_groups import (
    ChangeLifecycleGroupPayload, EntityLifecycleRead, LifecycleEntityType,
    LifecycleStageGroupRead, LifecycleStageGroupWrite,
)
from src.repositories.lifecycle_stage_groups_repository import (
    entity_model, lifecycle_stage_groups_repo,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Lifecycle Stage Groups"])

SETTINGS_FEATURE_ID = "settings-lifecycle-stage-groups"
ENTITY_FEATURES = {
    'data_product': 'data-products',
    'data_contract': 'data-contracts',
    'asset': 'assets',
}


def _http_error(e: CodedValueError) -> HTTPException:
    if isinstance(e, LifecycleGroupNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(e, (LifecycleGroupConflictError, LifecycleActionUnresolvedError)):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(e))


def _group_read(group) -> LifecycleStageGroupRead:
    """A stored row or an in-memory group of the service, as the API returns it."""
    if hasattr(group, 'stages') and isinstance(group.stages, dict):  # service Group
        return LifecycleStageGroupRead(
            id=group.id, name=group.name, entity_type=group.entity_type,
            is_default_for_type=group.is_default_for_type,
            stages=[s.as_dict() for s in group.stages.values()],
            transitions=[
                {'from_key': src, 'to_key': dst}
                for src, targets in group.transitions.items() for dst in targets
            ],
        )
    keys = {s.id: s.key for s in group.stages}
    return LifecycleStageGroupRead(
        id=group.id, name=group.name, description=group.description,
        entity_type=group.entity_type, is_default_for_type=group.is_default_for_type,
        stages=[{
            'key': s.key, 'label': s.label, 'category': s.category, 'color': s.color,
            'order': s.order, 'is_initial': s.is_initial,
        } for s in group.stages],
        transitions=[
            {'from_key': keys[t.from_stage_id], 'to_key': keys[t.to_stage_id]}
            for t in group.transitions
        ],
        created_by=group.created_by, updated_by=group.updated_by,
        created_at=group.created_at, updated_at=group.updated_at,
    )


async def _require(feature_id: str, level: FeatureAccessLevel, user, request: Request) -> None:
    if not await has_feature_permission(feature_id, level, user, request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")


# --------------------------------------------------------------------------- groups

@router.get('/lifecycle-stage-groups', response_model=List[LifecycleStageGroupRead])
async def list_lifecycle_stage_groups(
    request: Request,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    entity_type: Optional[LifecycleEntityType] = Query(None),
):
    """The groups of an entity type (default first), or of every type."""
    feature = ENTITY_FEATURES[entity_type] if entity_type else SETTINGS_FEATURE_ID
    await _require(feature, FeatureAccessLevel.READ_ONLY, current_user, request)
    rows = lifecycle_stage_groups_repo.list(db, entity_type)
    stored_types = {r.entity_type for r in rows}
    builtin = [
        _group_read(g) for g in lifecycle_service.groups(db, entity_type)
        if g.id is None and g.entity_type not in stored_types
    ]
    return [_group_read(r) for r in rows] + builtin


@router.get('/lifecycle-stage-groups/{group_id}', response_model=LifecycleStageGroupRead)
async def get_lifecycle_stage_group(
    group_id: str, request: Request, db: DBSessionDep, current_user: AuditCurrentUserDep,
):
    row = lifecycle_stage_groups_repo.get(db, group_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Lifecycle stage group not found")
    await _require(ENTITY_FEATURES[row.entity_type], FeatureAccessLevel.READ_ONLY,
                   current_user, request)
    return _group_read(row)


def _audit(audit_manager, db, request, user, action: str, details: dict) -> None:
    audit_manager.log_action(
        db=db, username=user.username if user else 'anonymous',
        ip_address=request.client.host if request.client else None,
        feature=SETTINGS_FEATURE_ID, action=action, success=True, details=details,
    )


@router.post('/lifecycle-stage-groups', response_model=LifecycleStageGroupRead,
             status_code=status.HTTP_201_CREATED)
async def create_lifecycle_stage_group(
    body: LifecycleStageGroupWrite,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        row = lifecycle_service.save_group(db, body.model_dump(), current_user.username)
    except CodedValueError as e:
        logger.info("Refused lifecycle stage group: %s", e)
        raise _http_error(e) from e
    _audit(audit_manager, db, request, current_user, 'CREATE',
           {'group_id': row.id, 'name': row.name, 'entity_type': row.entity_type})
    return _group_read(row)


@router.put('/lifecycle-stage-groups/{group_id}', response_model=LifecycleStageGroupRead)
async def update_lifecycle_stage_group(
    group_id: str,
    body: LifecycleStageGroupWrite,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        row = lifecycle_service.save_group(
            db, body.model_dump(), current_user.username, group_id=group_id,
        )
    except CodedValueError as e:
        logger.info("Refused lifecycle stage group %s: %s", group_id, e)
        raise _http_error(e) from e
    _audit(audit_manager, db, request, current_user, 'UPDATE',
           {'group_id': row.id, 'name': row.name, 'entity_type': row.entity_type})
    return _group_read(row)


@router.delete('/lifecycle-stage-groups/{group_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_lifecycle_stage_group(
    group_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        lifecycle_service.delete_group(db, group_id)
    except CodedValueError as e:
        logger.info("Refused deleting lifecycle stage group %s: %s", group_id, e)
        raise _http_error(e) from e
    _audit(audit_manager, db, request, current_user, 'DELETE', {'group_id': group_id})


# --------------------------------------------------------------------------- entities

def _entity(db, entity_type: str, entity_id: str) -> Any:
    from src.controller.lifecycle_service import _model_id

    model = entity_model(entity_type)
    key = _model_id(model, entity_id)
    entity = db.get(model, key) if key is not None else None
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


async def _is_admin(entity_type: str, user, request: Request) -> bool:
    return await has_feature_permission(
        ENTITY_FEATURES[entity_type], FeatureAccessLevel.ADMIN, user, request,
    )


async def _owns(db, entity_type: str, entity: Any, user, request: Request) -> bool:
    """Owner: a product's or contract's draft owner, owning team or project member;
    an asset's creator."""
    email = (user.email or '').lower() if user else ''
    if entity_type == 'asset':
        creator = (getattr(entity, 'created_by', None) or '').lower()
        return bool(creator) and creator in {email, (user.username or '').lower()}
    from src.common import product_read_rule as rule
    try:
        with db.begin_nested():
            return rule.caller_owns_product(
                db, entity, caller_email=user.email if user else None,
                caller_groups=(user.groups if user else None) or [],
            )
    except Exception:
        logger.exception("Ownership check failed for %s %s; denying", entity_type, entity.id)
        return False


async def _can_read(db, entity_type: str, entity: Any, user, request: Request) -> bool:
    if entity_type == 'data_contract':
        # The contracts' own read rule (version family, team, personal drafts)
        from src.routes.data_contracts_routes import (
            contract_read_scope, get_data_contracts_manager,
        )
        scope = await contract_read_scope(request, db, user)
        return get_data_contracts_manager(request).can_read_contract(db, entity, **scope)
    if await _is_admin(entity_type, user, request):
        return True
    if entity_type == 'asset':
        return True
    if lifecycle_service.category_of(db, entity_type, entity) in ('active', 'deprecated'):
        return True
    return await _owns(db, entity_type, entity, user, request)


@router.get('/lifecycle/{entity_type}/{entity_id}', response_model=EntityLifecycleRead)
async def get_entity_lifecycle(
    entity_type: LifecycleEntityType,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
):
    """The entity's group, its current stage and the stages it may move to."""
    await _require(ENTITY_FEATURES[entity_type], FeatureAccessLevel.READ_ONLY,
                   current_user, request)
    entity = _entity(db, entity_type, entity_id)
    if not await _can_read(db, entity_type, entity, current_user, request):
        raise HTTPException(status_code=404, detail="Entity not found")
    result = lifecycle_service.entity_lifecycle(db, entity_type, entity)
    # The UI offers "Change lifecycle" only to whom change-group accepts
    result['can_change_group'] = await _can_change_group(
        db, entity_type, entity, current_user, request,
    )
    return result


async def _can_change_group(db, entity_type: str, entity: Any, user, request: Request) -> bool:
    if not await has_feature_permission(
        ENTITY_FEATURES[entity_type], FeatureAccessLevel.READ_WRITE, user, request,
    ):
        return False
    return (await _is_admin(entity_type, user, request)
            or await _owns(db, entity_type, entity, user, request))


@router.post('/lifecycle/{entity_type}/{entity_id}/change-group',
             response_model=EntityLifecycleRead)
async def change_entity_lifecycle_group(
    entity_type: LifecycleEntityType,
    entity_id: str,
    body: ChangeLifecycleGroupPayload,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
):
    """Move the entity to another group of its type, in that group's first stage.

    Admins of the entity's feature and its owners only.
    """
    feature = ENTITY_FEATURES[entity_type]
    await _require(feature, FeatureAccessLevel.READ_WRITE, current_user, request)
    entity = _entity(db, entity_type, entity_id)
    if not await _can_change_group(db, entity_type, entity, current_user, request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin or an owner can change the lifecycle",
        )
    try:
        result = lifecycle_service.change_group(
            db, entity_type, entity_id, body.group_id, current_user.username,
        )
    except CodedValueError as e:
        logger.info("Refused lifecycle change of %s %s: %s", entity_type, entity_id, e)
        raise _http_error(e) from e
    audit_manager.log_action(
        db=db, username=current_user.username,
        ip_address=request.client.host if request.client else None,
        feature=feature, action='CHANGE_LIFECYCLE_GROUP', success=True,
        details={'entity_type': entity_type, 'entity_id': entity_id,
                 'group_id': body.group_id, 'status': result['status']},
    )
    return result


def register_routes(app):
    app.include_router(router)
    logger.info("Lifecycle stage group routes registered")
