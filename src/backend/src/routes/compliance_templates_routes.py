"""API routes for Compliance Templates.

Two RBAC surfaces:
- ``settings-compliance-templates`` gates admin template *definition* management.
- ``compliance-template-values`` gates per-entity value read (READ_ONLY) vs
  write (READ_WRITE).
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.common.authorization import PermissionChecker
from src.common.dependencies import CurrentUserDep, DBSessionDep
from src.common import product_read_rule
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.compliance_templates_manager import (
    ComplianceConflictError,
    ComplianceNotFoundError,
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

logger = get_logger(__name__)

router = APIRouter(prefix="/api/compliance-templates", tags=["Compliance Templates"])

ADMIN_FEATURE_ID = "settings-compliance-templates"
VALUES_FEATURE_ID = "compliance-template-values"


def _assert_can_read_values(request: Request, db, current_user, entity_type: str, entity_id: str) -> None:
    """Reading a product's compliance values follows the product read rule.

    A product the caller can't read (a draft or proposed product they don't own, or
    a missing one) answers 404, the same as the product page. Other entity types
    keep the feature check.
    """
    if entity_type != "data_product":
        return
    from src.repositories.data_products_repository import data_product_repo
    # The product page's read gate (published, admin, owner, pending reviewer). It
    # takes an unused manager argument and fails closed on error.
    from src.routes.data_product_routes import _caller_can_read_product

    product = data_product_repo.get(db=db, id=entity_id)
    if product is None or not _caller_can_read_product(request, db, current_user, None, product):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data product not found")


def _is_values_admin(request: Request, current_user) -> bool:
    """Whether the caller holds ADMIN on compliance-template-values, resolved like the feature checks."""
    if not current_user:
        return False
    auth_manager = getattr(request.app.state, "authorization_manager", None)
    if not auth_manager:
        return False
    from src.common.authorization import effective_permissions_for_request

    eff = effective_permissions_for_request(request, current_user.email, current_user.groups or [], auth_manager)
    return auth_manager.has_permission(eff, VALUES_FEATURE_ID, FeatureAccessLevel.ADMIN)


def _assert_can_edit_values(request: Request, db, current_user, entity_type: str, entity_id: str) -> None:
    """Writing a product's compliance values needs the same edit rights as editing the product.

    Admin, or an owner of the product (draft owner, owning team, project member), as the
    product routes decide (``product_read_rule``). The feature-level permission alone is
    not enough.

    Any other entity type fails closed: only an admin (ADMIN on compliance-template-values)
    may write its values. #1512 must add the owner check for tables and views here before it
    lets Stewards and Producers write them; until then no owner rule exists for them.
    """
    if entity_type != "data_product":
        if not _is_values_admin(request, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can fill compliance values for this entity type",
            )
        return
    from src.repositories.data_products_repository import data_product_repo

    product = data_product_repo.get(db=db, id=entity_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data product not found")
    try:
        if product_read_rule.is_product_read_admin(request, current_user):
            return
        owns = product_read_rule.caller_owns_product(
            db,
            product,
            caller_email=current_user.email if current_user else None,
            caller_groups=(current_user.groups if current_user else None) or [],
        )
    except Exception:
        # Fail closed: an ownership lookup that errors denies the write
        logger.exception("Ownership check failed for compliance values of product %s", entity_id)
        owns = False
    if not owns:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only fill compliance values for products you own",
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
    """Delete a template and its fields. Answers 409 while any product still has values for it. Admin only."""
    try:
        compliance_templates_manager.delete_template(db, template_id=template_id)
    except ComplianceConflictError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
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
    """Update a field. Destructive edits (value_type change, enum removal with values) answer 409."""
    try:
        return compliance_templates_manager.update_field(db, field_id=field_id, payload=body)
    except ComplianceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ComplianceConflictError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
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
    current_user: CurrentUserDep,
    _: None = Depends(PermissionChecker(VALUES_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Composed read: { template, fields, values } for an entity. Read-only allowed; a product
    the caller can't read answers 404."""
    _assert_can_read_values(request, db, current_user, entity_type, entity_id)
    return compliance_templates_manager.read_for_entity(db, entity_type=entity_type, entity_id=entity_id)


@router.get("/entities/{entity_type}/{entity_id}/completeness", response_model=ComplianceCompletenessRead)
async def entity_completeness(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    _: None = Depends(PermissionChecker(VALUES_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Advisory completeness result for an entity. Never blocks; read-only allowed. Its
    missing-field list reveals values, so the read rule applies here too."""
    _assert_can_read_values(request, db, current_user, entity_type, entity_id)
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
    _: None = Depends(PermissionChecker(VALUES_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Replace-all write of an entity's values (the materialization event). Owners and admins only."""
    _assert_can_edit_values(request, db, current_user, entity_type, entity_id)
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
