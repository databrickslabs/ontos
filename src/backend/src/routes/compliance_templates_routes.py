"""API routes for Compliance Templates.

Two RBAC surfaces:
- ``settings-compliance-templates`` gates admin template *definition* management.
- ``compliance-template-values`` gates per-entity value read (READ_ONLY) vs
  write (READ_WRITE).

Values of table and view assets (``entity_type = "asset"``) also follow the
asset routes' read and edit rules (see ``_ensure_entity_access``).
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.common.authorization import PermissionChecker, get_user_details_from_sdk
from src.common.dependencies import CurrentUserDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.manager_dependencies import get_auth_manager
from src.controller.assets_manager import assets_manager
from src.controller.authorization_manager import AuthorizationManager
from src.controller.compliance_template_assets import (
    ASSET_ENTITY_TYPE,
    ComplianceTemplateAssetError,
    resolve_template_asset,
)
from src.controller.compliance_templates_manager import (
    ComplianceTemplateError,
    compliance_templates_manager,
)
from src.models.compliance_templates import (
    ComplianceCompletenessRead,
    ComplianceFieldCreate,
    ComplianceFieldRead,
    ComplianceFieldsReorder,
    ComplianceTemplateCreate,
    ComplianceTemplateRead,
    ComplianceTemplateUpdate,
    ComplianceValuesReplace,
    EntityComplianceRead,
)
from src.models.users import UserInfo

logger = get_logger(__name__)

router = APIRouter(prefix="/api/compliance-templates", tags=["Compliance Templates"])

ADMIN_FEATURE_ID = "settings-compliance-templates"
VALUES_FEATURE_ID = "compliance-template-values"
ASSETS_FEATURE_ID = "assets"


async def _has_feature(
    request: Request,
    user: UserInfo,
    auth_manager: AuthorizationManager,
    feature_id: str,
    level: FeatureAccessLevel,
) -> bool:
    """Whether the user has ``feature_id`` at ``level`` (the ``PermissionChecker`` rule)."""
    try:
        await PermissionChecker(feature_id, level)(request, user, auth_manager)
        return True
    except HTTPException as e:
        if e.status_code == status.HTTP_403_FORBIDDEN:
            return False
        raise


async def _ensure_entity_access(
    request: Request,
    db: Session,
    user: UserInfo,
    auth_manager: AuthorizationManager,
    *,
    entity_type: str,
    entity_id: str,
    write: bool,
) -> None:
    """Host entity checks on top of the values feature (only assets have them).

    Asset values follow the asset routes' rules: writing needs ``assets`` at
    READ_WRITE (as editing the asset); reading needs that, or a link to a data
    product the user can access (as ``GET /api/assets/{id}``). The asset must
    be a table or a view.
    """
    if entity_type != ASSET_ENTITY_TYPE:
        return
    try:
        asset = resolve_template_asset(db, entity_id)
    except ComplianceTemplateAssetError as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_detail())
    if await _has_feature(
        request, user, auth_manager, ASSETS_FEATURE_ID, FeatureAccessLevel.READ_WRITE
    ):
        return
    if not write:
        dpm = getattr(request.app.state, "data_products_manager", None)
        if dpm is not None and assets_manager.is_asset_accessible(
            db, asset_id=asset.id, data_products_manager=dpm, is_admin=False
        ):
            return
    code = (
        "compliance_template_asset_write_forbidden"
        if write
        else "compliance_template_asset_read_forbidden"
    )
    message = (
        "You can't change the compliance values of this asset."
        if write
        else "You can't view the compliance values of this asset."
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": message, "params": {"assetId": str(asset.id)}},
    )


# ----- Admin: template definitions ----------------------------------------

@router.get("", response_model=list[ComplianceTemplateRead])
async def list_templates(
    db: DBSessionDep,
    entity_type: str | None = None,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """List templates, optionally filtered by bound entity type. Admin surface."""
    return compliance_templates_manager.list_templates(db, entity_type=entity_type)


@router.post("", response_model=ComplianceTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: ComplianceTemplateCreate,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Create a template (optionally with inline fields). Admin only."""
    try:
        return compliance_templates_manager.create_template(
            db, payload=body, user_email=current_user.email if current_user else None
        )
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating compliance template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create compliance template")


@router.put("/{template_id}", response_model=ComplianceTemplateRead)
async def update_template(
    template_id: UUID,
    body: ComplianceTemplateUpdate,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Update a template's safe attributes (name, description). Admin only."""
    update_data = body.model_dump(exclude_unset=True)
    try:
        return compliance_templates_manager.update_template(db, template_id=template_id, update_data=update_data)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{template_id}/activate", response_model=ComplianceTemplateRead)
async def activate_template(
    template_id: UUID,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Activate a template, deactivating any currently-active one for its entity type."""
    try:
        return compliance_templates_manager.set_active(db, template_id=template_id, active=True)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{template_id}/deactivate", response_model=ComplianceTemplateRead)
async def deactivate_template(
    template_id: UUID,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Deactivate a template."""
    try:
        return compliance_templates_manager.set_active(db, template_id=template_id, active=False)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Delete a template and its fields/values. Admin only."""
    try:
        compliance_templates_manager.delete_template(db, template_id=template_id)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ----- Admin: field management (safe & destructive) -------------------------

@router.post("/{template_id}/fields", response_model=ComplianceFieldRead, status_code=status.HTTP_201_CREATED)
async def add_template_field(
    template_id: UUID,
    body: ComplianceFieldCreate,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Add a field to a template. Safe to call on active template."""
    try:
        return compliance_templates_manager.add_field(db, template_id=template_id, payload=body)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding compliance field: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add field")


@router.put("/{template_id}/fields/reorder", response_model=list[ComplianceFieldRead])
async def reorder_template_fields(
    template_id: UUID,
    body: ComplianceFieldsReorder,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Reorder fields and reassign groups. Admin only."""
    try:
        order_map = [{"id": f.id, "group_title": f.group_title, "group_order": f.group_order, "field_order": f.field_order} for f in body.fields]
        return compliance_templates_manager.reorder_fields(db, template_id=template_id, order_map=order_map)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error reordering fields: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reorder fields")


@router.put("/{template_id}/fields/{field_id}", response_model=ComplianceFieldRead)
async def update_template_field(
    template_id: UUID,
    field_id: UUID,
    body: dict,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Update a field's safe attributes or add an enum value. Guards against destructive edits."""
    try:
        return compliance_templates_manager.update_field(db, field_id=field_id, payload=body)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating field: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update field")


@router.delete("/{template_id}/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template_field(
    template_id: UUID,
    field_id: UUID,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Delete a field. Guarded: cannot delete if stored values exist."""
    try:
        compliance_templates_manager.delete_field(db, field_id=field_id)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting field: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete field")


# ----- Per-entity: composed read + replace-all write -----------------------

@router.get("/entities/{entity_type}/{entity_id}", response_model=EntityComplianceRead)
async def read_entity_compliance(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    user: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    _: None = Depends(PermissionChecker(VALUES_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Composed read: { template, fields, values } for an entity. Read-only allowed."""
    await _ensure_entity_access(
        request, db, user, auth_manager,
        entity_type=entity_type, entity_id=entity_id, write=False,
    )
    return compliance_templates_manager.read_for_entity(db, entity_type=entity_type, entity_id=entity_id)


@router.get("/entities/{entity_type}/{entity_id}/completeness", response_model=ComplianceCompletenessRead)
async def entity_completeness(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    user: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    _: None = Depends(PermissionChecker(VALUES_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Advisory completeness result for an entity. Never blocks; read-only allowed."""
    await _ensure_entity_access(
        request, db, user, auth_manager,
        entity_type=entity_type, entity_id=entity_id, write=False,
    )
    applicable = compliance_templates_manager.has_active_template(db, entity_type=entity_type)
    result = compliance_templates_manager.check_completeness(db, entity_type=entity_type, entity_id=entity_id)
    return ComplianceCompletenessRead(
        applicable=applicable,
        passed=result.passed,
        missing=result.missing,
        messages=result.messages,
    )


@router.put("/entities/{entity_type}/{entity_id}/values", response_model=EntityComplianceRead)
async def replace_entity_values(
    entity_type: str,
    entity_id: str,
    body: ComplianceValuesReplace,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    user: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    _: None = Depends(PermissionChecker(VALUES_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Replace-all write of an entity's values (the materialization event)."""
    await _ensure_entity_access(
        request, db, user, auth_manager,
        entity_type=entity_type, entity_id=entity_id, write=True,
    )
    try:
        return compliance_templates_manager.replace_values(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            writes=body.values,
            user_email=current_user.email if current_user else None,
        )
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error writing compliance values: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to write compliance values")


def register_routes(app):
    app.include_router(router)
    logger.info("Compliance templates routes registered")
